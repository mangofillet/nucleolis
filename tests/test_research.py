"""Executable hypothesis semantics, tested without model calls or clinical claims."""
import asyncio
import copy

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import AsyncOpenAI
from pydantic import ValidationError

from nucleolis.api.main import app
from nucleolis.api.research import snapshot_dependency
from nucleolis.api.simulation import settings_dependency
from nucleolis.graph.queries import Snapshot
from nucleolis.llm.settings import Settings
from nucleolis.schemas.research import ResearchRequest, ResearchResponse
from nucleolis.services import research
from test_contract import _snapshot_payload


@pytest.fixture
def snap():
    return Snapshot(_snapshot_payload(), path=None)


def run(q, snap, **kwargs):
    parsed = research.parse_local(q, snap)
    assert parsed is not None
    return research.analyze(ResearchRequest(query=q, **kwargs), snap, parsed)


def test_question_uses_subject_for_outgoing_and_object_for_incoming(snap):
    outgoing = run("What does AAA activate?", snap)
    incoming = run("What activates BBB?", snap)
    assert {e.id for e in outgoing.links} == {"clm_pos"}
    assert {e.id for e in incoming.links} == {"clm_pos"}
    assert incoming.target_id == "HGNC:2" and incoming.source_id is None
    assert incoming.paths[0].node_ids == ["HGNC:1", "HGNC:2"]


def test_intervention_target_before_source_keeps_roles_and_both_signs(snap):
    result = run("What happens to BBB if I decrease AAA?", snap)
    assert result.source_id == "HGNC:1" and result.target_id == "HGNC:2"
    assert {p.direction for p in result.paths} == {-1, 1}
    assert result.paths[0].intervention == "decrease"
    assert next(n for n in result.nodes if n.id == "HGNC:2").state == "mixed"
    assert next(n for n in result.nodes if n.id == "HGNC:2").lane == 2


def test_pair_hypothesis_preserves_opposing_direction(snap):
    result = run("Does AAA activate BBB?", snap)
    assert {p.assessment for p in result.paths} == {"supports_direction", "opposes_direction"}
    assert all(n.state == "unknown" for n in result.nodes)


def test_inhibiting_source_is_not_a_request_to_find_its_inhibitors(snap):
    result = run("Could inhibiting AAA reduce CCC?", snap)
    assert result.plan.perturbation == "decrease"
    assert result.source_id == "HGNC:1" and result.target_id == "HGNC:3"
    assert {p.assessment for p in result.paths} == {"supports_direction", "opposes_direction"}
    assert "clm_bind" not in {e.id for e in result.links}
    assert all(len(p.assumptions) == 2 for p in result.paths)


def test_source_only_perturbation_does_not_require_readout(snap):
    result = run("What happens if I knock out AAA?", snap)
    assert result.status == "completed" and result.target_id is None
    assert result.plan.perturbation == "knockout"
    assert all(p.direction in {-1, 1} for p in result.paths)


def test_inverse_intervention_is_based_on_signed_direction_not_inverted_edges(snap):
    result = run("Which targets could reduce CCC?", snap)
    for path in result.paths:
        assert path.node_ids[-1] == "HGNC:3"
        factor = 1 if path.intervention == "increase" else -1
        assert factor * path.direction == -1
    assert "0 chemical entities" in result.answer


def test_unresolved_readout_produces_empty_new_result(snap):
    result = run("What happens to neurodegeneration if I decrease AAA?", snap)
    assert result.status == "needs_clarification"
    assert result.nodes == [] and result.paths == []
    assert "neurodegeneration" in result.answer


def test_cell_context_is_reported_as_unapplied_not_silently_discarded(snap):
    result = run("What does AAA activate in microglia?", snap)
    # The question is answerable; the context this snapshot cannot filter on is disclosed, not dropped.
    assert result.status == "completed" and result.links
    assert any("microglia" in text and "NOT applied" in text for text in result.limitations)


def test_drug_question_answers_with_upstream_regulators_not_a_refusal(snap):
    parsed = research.plan("target_discovery", target="BBB")
    result = research.analyze(ResearchRequest(query="Which drugs target BBB?"), snap, parsed)
    assert result.status == "completed" and result.plan.operation == "incoming"
    assert result.target_id == "HGNC:2" and result.links
    assert any("compound" in text.casefold() for text in result.limitations)


def test_readout_outside_the_snapshot_is_disclosed_not_refused(snap):
    # The constrained entity enum makes a parser repeat the only allowed mention in both slots.
    parsed = research.plan("connection", source="AAA", target="AAA", desired=1)
    result = research.analyze(ResearchRequest(query="How does AAA cause neuron death?"), snap, parsed)
    assert result.status == "completed" and result.links
    assert result.source_id == "HGNC:1" and result.target_id is None
    assert any("readout" in text.casefold() for text in result.limitations)


def test_descriptive_question_describes_the_entity_we_hold(snap):
    result = run("What is AAA?", snap)
    assert result.plan.operation == "overview" and result.status == "completed"
    assert result.source_id == "HGNC:1" and result.links


def test_unsupported_question_naming_a_known_entity_falls_back_to_overview(snap):
    parsed = research.plan("unsupported", source="AAA", reason="not executable as asked")
    result = research.analyze(ResearchRequest(query="Find a cure using AAA"), snap, parsed)
    assert result.plan.operation == "overview" and result.status == "completed" and result.links
    assert result.target_id is None


def test_species_filter_checks_evidence_not_human_gene_namespace(snap):
    assert run("What does AAA activate?", snap, species="human").status == "insufficient_evidence"
    payload = _snapshot_payload()
    payload["contexts"].append({"id": "human", "taxon_id": 9606})
    payload["evidence"][0]["context_id"] = "human"
    filtered = run("What does AAA activate in human?", Snapshot(payload, None))
    assert filtered.species == "human"
    assert filtered.links[0].evidence_ids == ["evd_1"]
    assert filtered.links[0].publication_ids == ["PMID:1"]


def test_retracted_and_negated_evidence_cannot_drive_paths():
    payload = _snapshot_payload()
    payload["documents"][0]["retraction_status"] = "retracted"
    payload["evidence"][1]["negated"] = True
    result = run("What does AAA activate?", Snapshot(payload, None))
    assert result.status == "insufficient_evidence" and result.links == []


def test_missing_route_is_not_a_negative_result(snap):
    result = run("Does CCC activate AAA?", snap)
    assert result.status == "insufficient_evidence"
    assert "does not establish" in result.answer


def test_display_cap_preserves_both_signs_and_reports_omissions(snap):
    result = run("Show mechanism of AAA", snap, max_paths=2)
    assert len(result.paths) == 2 and {p.direction for p in result.paths} == {-1, 1}
    assert result.paths_omitted == 2
    assert len(result.nodes) <= 24 and len(result.links) <= 48
    assert not result.search_truncated


def test_response_rejects_wrong_direction_and_duplicate_ids(snap):
    result = run("What does AAA activate?", snap).model_dump()
    bad = copy.deepcopy(result)
    bad["paths"][0]["node_ids"].reverse()
    with pytest.raises(ValidationError):
        ResearchResponse.model_validate(bad)
    result["nodes"].append(result["nodes"][0])
    with pytest.raises(ValidationError):
        ResearchResponse.model_validate(result)


def test_common_queries_never_require_a_model(snap, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Common query made an LLM call")
    monkeypatch.setattr(research, "AsyncOpenAI", forbidden)
    parsed, parser = asyncio.run(research.interpret("What does AAA activate?", snap, Settings()))
    assert parsed.operation == "outgoing" and parser == "local_grammar"
    unknown, _ = asyncio.run(research.interpret("invent a new molecule", snap, Settings()))
    assert unknown.operation == "unsupported"


def test_research_and_ask_routes_work_without_keys_and_validate_input(snap):
    app.dependency_overrides[snapshot_dependency] = lambda: snap
    app.dependency_overrides[settings_dependency] = lambda: Settings()
    try:
        client = TestClient(app)
        for endpoint in ("/ask", "/api/research"):
            result = client.post(endpoint, json={"query": "What does AAA activate?"})
            assert result.status_code == 200
            assert result.json()["links"][0]["id"] == "clm_pos"
            assert client.post(endpoint, json={"query": "", "extra": True}).status_code == 422
        caps = client.get("/api/research/capabilities").json()
        assert caps["local_questions_available"] and not caps["language_parser_configured"]
    finally:
        app.dependency_overrides.clear()


def test_free_wording_uses_strict_schema_and_cannot_invent_mentions(snap, monkeypatch):
    async def case(invent=False):
        def respond(request):
            import json
            body = json.loads(request.content)
            assert body["response_format"]["json_schema"]["strict"]
            assert body["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
            parsed = research.plan("intervention", source="fabricated" if invent else "AAA", target="CCC", perturbation="decrease")
            return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 0, "model": "test", "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": parsed.model_dump_json()}}]})
        client = AsyncOpenAI(api_key="fixture", base_url="https://fixture.invalid", http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
        monkeypatch.setattr(research, "AsyncOpenAI", lambda **kwargs: client)
        return await research.interpret("My hypothesis is that lowering AAA changes CCC", snap, Settings(nebius_model="test", nebius_api_key="fixture"))
    result, parser = asyncio.run(case())
    assert result.source == "AAA" and parser == "nebius"
    invalid, _ = asyncio.run(case(True))
    assert invalid.operation == "unsupported"


def test_two_route_cap_keeps_opposite_sign_at_a_different_depth():
    payload = _snapshot_payload()
    payload["claims"] = [c for c in payload["claims"] if c["id"] != "clm_pos"]
    opposite = copy.deepcopy(next(c for c in payload["claims"] if c["id"] == "clm_hop"))
    opposite.update(id="hop_negative", predicate="inhibits", effect_sign=-1, evidence_ids=["hop_evidence"])
    payload["claims"].append(opposite)
    passage = copy.deepcopy(payload["evidence"][-1])
    passage.update(id="hop_evidence", claim_id="hop_negative")
    payload["evidence"].append(passage)
    result = run("Show mechanism of AAA", Snapshot(payload, None), max_paths=2)
    assert len(result.paths) == 2 and {p.direction for p in result.paths} == {-1, 1}
    assert result.paths_omitted == 1


@pytest.mark.parametrize("readout", ["AAA aggregation", "AAA pathology", "AAA mutation", "AAA deficiency"])
def test_distinct_biological_readouts_are_not_silently_replaced_with_gene(snap, readout):
    result = run(f"Does BBB reduce {readout}?", snap)
    assert result.status == "needs_clarification" and not result.paths
    assert readout in result.answer


def test_conflicting_species_requires_clarification(snap):
    result = run("What does AAA activate in mouse?", snap, species="human")
    assert result.status == "needs_clarification" and result.nodes == []
    assert "mouse" in result.answer and "human" in result.answer


def test_normalized_plan_has_consistent_focus_identifiers_and_does_not_mutate_input(snap):
    parsed = research.plan("overview", target="AAA")
    result = research.analyze(ResearchRequest(query="Tell me about AAA"), snap, parsed)
    assert result.source_id == "HGNC:1" and result.target_id is None
    assert result.plan.source == "AAA" and result.plan.target is None
    assert parsed.source is None and parsed.target == "AAA"
    parsed = research.plan("incoming", source="BBB")
    result = research.analyze(ResearchRequest(query="What regulates BBB?"), snap, parsed)
    assert result.source_id is None and result.target_id == "HGNC:2"


def test_comparison_and_unsupported_fallback_disclose_the_unperformed_request(snap):
    result = run("Compare AAA and BBB", snap)
    assert any("comparison" in s and "not performed" in s for s in result.limitations)
    parsed = research.plan("unsupported", source="AAA", reason="Dose design is unsupported")
    result = research.analyze(ResearchRequest(query="Design a dose for AAA"), snap, parsed)
    assert any("Dose design is unsupported" in s for s in result.limitations)


def test_drug_target_question_runs_locally(snap, monkeypatch):
    monkeypatch.setattr(research, "AsyncOpenAI", lambda **kwargs: pytest.fail("Unexpected provider call"))
    parsed, parser = asyncio.run(research.interpret("Which drugs target BBB?", snap, Settings()))
    result = research.analyze(ResearchRequest(query="Which drugs target BBB?"), snap, parsed, parser)
    assert result.parser == "local_grammar" and result.plan.operation == "incoming"
    assert any("0 compound entities" in s for s in result.limitations)


@pytest.mark.parametrize("case", ["malformed", "refusal", "truncated", "http_error", "timeout", "no_choices"])
def test_research_provider_failures_return_explicit_bounded_results(snap, monkeypatch, case):
    calls = []
    def handler(request):
        calls.append(1)
        if case == "timeout":
            raise httpx.ReadTimeout("fixture timeout", request=request)
        if case == "http_error":
            return httpx.Response(401, json={"error": {"message": "private provider detail"}})
        choices = [{"index": 0, "finish_reason": "length" if case == "truncated" else "stop",
                    "message": {"role": "assistant", "content": "{}",
                                "refusal": "refused" if case == "refusal" else None}}]
        return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 0,
                                        "model": "test", "choices": [] if case == "no_choices" else choices})
    async def invoke():
        client = AsyncOpenAI(api_key="fixture", max_retries=0,
                             http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        monkeypatch.setattr(research, "AsyncOpenAI", lambda **kwargs: client)
        parsed, parser = await research.interpret("My hypothesis concerns AAA", snap,
                                                 Settings(nebius_model="test", nebius_api_key="fixture"))
        return research.analyze(ResearchRequest(query="My hypothesis concerns AAA"), snap, parsed, parser)
    result = asyncio.run(invoke())
    assert result.status == "needs_clarification" and not result.nodes
    assert 1 <= len(calls) <= 2
    assert "private provider detail" not in result.model_dump_json()


def test_draft_configuration_requires_parser_model(snap):
    app.dependency_overrides[snapshot_dependency] = lambda: snap
    app.dependency_overrides[settings_dependency] = lambda: Settings(nebius_api_key="fixture", anthropic_api_key="fixture")
    try:
        assert not TestClient(app).get("/api/research/capabilities").json()["research_draft_configured"]
    finally:
        app.dependency_overrides.clear()


def test_search_deadline_reports_truncation(snap, monkeypatch):
    ticks = iter([0, 2])
    monkeypatch.setattr(research.time, "monotonic", lambda: next(ticks))
    result = run("Show mechanism of AAA", snap)
    assert result.search_truncated and result.status == "insufficient_evidence"
    assert any("Omitted paths" in s for s in result.limitations)


def test_duplicate_paths_are_rejected(snap):
    result = run("What does AAA activate?", snap).model_dump()
    result["paths"].append(result["paths"][0])
    with pytest.raises(ValidationError, match="Duplicate path"):
        ResearchResponse.model_validate(result)
