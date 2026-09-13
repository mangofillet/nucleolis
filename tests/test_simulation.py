"""Scientific semantics and API integration checked without live providers."""
import asyncio
import copy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from nucleolis.analysis import adapter, boolean, confidence, demo, grounding, signed_paths
from nucleolis.api.main import app
from nucleolis.api.simulation import service_dependency, settings_dependency
from nucleolis.llm.common import ProviderError
from nucleolis.llm.settings import Settings
from nucleolis.schemas.simulation import (
    BooleanManifest, ClaimMapping, EntityMention, EvidenceReview, GroundedQuery, Limits,
    ParsedQuery, Rule, SimulateTargetRequest, SimulateTargetResponse, StatementRef,
)
from nucleolis.services.simulate_target import SimulationService, validate_citations


@pytest.fixture
def data():
    return demo.fixture()


def query():
    return GroundedQuery(source_id="DEMO:A", target_id="DEMO:C", intervention_direction=-1, context_id="demo_context")


def test_sign_propagation_and_belief(data):
    snap, review, _ = data
    graph = adapter.adapt(snap, review, "DEMO:A", "DEMO:C")
    result = signed_paths.analyze(graph, query(), 1)
    assert result.category == "supportive_only"
    assert result.paths[0].implied_direction == 1
    assert result.paths[0].claim_ids == ["demo_ab", "demo_bc"]
    assert result.paths[0].belief_score == 0.8
    assert confidence.assess(graph).distinct_publication_count == 2


def test_parallel_conflict_not_majority_vote(data):
    snap, review, _ = data
    graph = adapter.adapt(snap, review, "DEMO:A", "DEMO:C")
    for i in range(8):
        edge = graph.links[1].model_copy(deep=True, update={"id": f"opposite_{i}", "sign": 1})
        graph.links.append(edge)
        graph.mappings[edge.id] = graph.mappings["demo_bc"]
    result = signed_paths.analyze(graph, query(), 1)
    assert result.category == "conflicting"
    assert {p.implied_direction for p in result.paths} == {-1, 1}
    assert result.total_paths == 9 and result.display_paths_omitted == 4


@pytest.mark.parametrize("change", ["unreviewed", "negated", "retracted", "context", "unsigned", "unchecked", "mapping"])
def test_eligibility_gates(data, change):
    snap, review, _ = data
    if change == "unreviewed":
        review.reviews[0].approved = False
    elif change == "negated":
        snap.evidence["e_demo_ab"]["negated"] = True
    elif change == "retracted":
        snap.documents["DEMO-PAPER:demo_ab"]["retraction_status"] = "retracted"
    elif change == "context":
        snap.evidence["e_demo_ab"]["context_id"] = "ctx_unknown"
    elif change == "unsigned":
        snap.claims["demo_ab"]["effect_sign"] = None
    elif change == "unchecked":
        review.reviews[0].source_checked = False
    else:
        review.mappings = review.mappings[1:]
    graph = adapter.adapt(snap, review, "DEMO:A", "DEMO:C")
    assert signed_paths.analyze(graph, query(), None).category == "insufficient_evidence"


def test_state_mismatch_does_not_compose(data):
    snap, review, _ = data
    review.mappings[1].source_state = "abundance"
    graph = adapter.adapt(snap, review, "DEMO:A", "DEMO:C")
    assert signed_paths.analyze(graph, query(), None).total_paths == 0


def test_exclusion_copy_and_alternative_support(data):
    snap, review, _ = data
    raw = copy.deepcopy(snap.evidence["e_demo_ab"])
    raw.update(id="second_evidence", document_id="DEMO-PAPER:second")
    snap.evidence[raw["id"]] = raw
    snap.documents[raw["document_id"]] = dict(id=raw["document_id"], retraction_status="not_retracted")
    review.reviews.append(review.reviews[0].model_copy(update={"evidence_id": raw["id"]}))
    before = adapter.adapt(snap, review, "DEMO:A", "DEMO:C")
    after = adapter.adapt(snap, review, "DEMO:A", "DEMO:C", {"DEMO-PAPER:demo_ab"})
    assert before.links[0].papers == 2 and after.links[0].papers == 1
    assert signed_paths.analyze(after, query(), 1).total_paths == 1
    lost = adapter.adapt(snap, review, "DEMO:A", "DEMO:C", {"DEMO-PAPER:demo_bc"})
    assert signed_paths.analyze(lost, query(), 1).total_paths == 0
    assert "e_demo_ab" in snap.evidence


def test_missing_belief_and_duplicate_statement_count(data):
    snap, review, _ = data
    review.statements[0].belief = None
    graph = adapter.adapt(snap, review, "DEMO:A", "DEMO:C")
    assessment = confidence.assess(graph)
    assert assessment.belief_coverage == 0.5
    assert graph.links[0].belief is None
    assert signed_paths.analyze(graph, query(), 1).paths[0].belief_score is None
    graph.links.append(graph.links[1])
    assert confidence.assess(graph).unique_statement_count == 2


def test_unknown_review_does_not_become_curated(data):
    snap, _, _ = data
    graph = adapter.adapt(snap, None, "DEMO:A", "DEMO:C")
    assert graph.links == [] and confidence.assess(graph).weakest_belief is None


def test_stale_manifest_and_boolean_sign_rejected(data):
    snap, review, _ = data
    review.snapshot_checksum = "different"
    with pytest.raises(adapter.ManifestError):
        adapter.validate_review(review, snap)
    with pytest.raises(ValidationError):
        GroundedQuery(source_id="a", target_id="b", intervention_direction=True)


def test_budget_and_deterministic_paths(data):
    snap, review, _ = data
    graph = adapter.adapt(snap, review, "DEMO:A", "DEMO:C")
    normal = signed_paths.analyze(graph, query(), 1)
    assert normal == signed_paths.analyze(graph, query(), 1)
    limited = signed_paths.analyze(graph, query(), 1, Limits(candidate_budget=1))
    assert limited.completion == "truncated"
    assert signed_paths.exclusion_effect(normal, limited) == "indeterminate"


def test_boolean_clamp_baseline_and_synchronous_updates(data):
    _, _, model = data
    result = boolean.compare(model, "DEMO:A", "knockout")
    assert result.baseline.terminal == {"a": 1, "b": 1, "c": 0}
    assert result.perturbed.terminal == {"a": 0, "b": 0, "c": 1}
    assert result.perturbed.trajectory[1].values["c"] == 0  # reads old b
    assert all(row.values["a"] == 0 for row in result.perturbed.trajectory)
    assert boolean.execute(model, {"a": 1}) == result.baseline
    assert len(result.flips) == 3
    with pytest.raises(ValueError):
        boolean.compare(model, "DEMO:A", "decrease")


def test_boolean_cycles_step_limit_and_threshold_tie(data):
    _, _, model = data
    model.rules[0] = Rule(id="rule_a", target="a", operation="not", regulators=["a"], assumption="cycle fixture")
    assert boolean.execute(model).completion == "cycle"
    assert boolean.execute(model, steps=1).completion == "max_steps"
    model.rules[0] = Rule(id="rule_a", target="a", operation="signed_threshold", regulators=["a"], signs=[1], threshold=1, assumption="hold on tie")
    assert boolean.execute(model).terminal["a"] == 1


def test_grounding_must_match_catalog(data):
    snap, _, _ = data
    parsed = asyncio.run(demo.DemoParser().parse(demo.DEMO_QUERY, []))
    parsed.source_entity.candidate_id = "MADE:UP"
    with pytest.raises(ValueError):
        grounding.ground(parsed, snap, None)
    parsed.source_entity.candidate_id = "DEMO:A"
    parsed.intervention = "unspecified"
    assert grounding.ground(parsed, snap, None)[0] is None


def test_grounding_uses_stated_intervention_not_intent_label(data):
    snap, _, _ = data
    parsed = asyncio.run(demo.DemoParser().parse(demo.DEMO_QUERY, []))
    parsed.query_intent = "mechanism"
    grounded, reason = grounding.ground(parsed, snap, None)
    assert reason is None and grounded.source_id == "DEMO:A" and grounded.target_id == "DEMO:C"
    parsed.query_intent = "unsupported"
    assert grounding.ground(parsed, snap, None)[0] is None


def test_service_success_and_claude_failure_preserves_graph(data):
    snap, review, model = data
    request = SimulateTargetRequest(query=demo.DEMO_QUERY, demo=True, context_id="demo_context")
    service = SimulationService(Settings(), demo.DemoParser(), demo.DemoScientist())
    response = asyncio.run(service.run(request, snap, review, model))
    assert response.status == "completed" and len(response.nodes) == 3
    SimulateTargetResponse.model_validate_json(response.model_dump_json())
    class FailingScientist:
        model = "failing_test_provider"
        async def synthesize(self, bundle):
            raise ProviderError("synthesis", "timeout", "test timeout", 504)
    service.scientist = FailingScientist()
    failed = asyncio.run(service.run(request, snap, review, model))
    assert failed.status == "partial" and failed.synthesis is None
    assert failed.nodes == response.nodes and failed.analysis == response.analysis


def test_boolean_endpoint_and_demo_opt_in():
    app.dependency_overrides[settings_dependency] = lambda: Settings(demo_enabled=True)
    try:
        with TestClient(app) as client:
            result = client.post("/api/simulate-target", json={"query": demo.DEMO_QUERY, "demo": True,
                                 "context_id": "demo_context", "method": "illustrative_boolean",
                                 "boolean_model_id": "synthetic_boolean_v1"})
            assert result.status_code == 200, result.text
            body = result.json()
            assert body["synthetic"] and body["analysis"]["boolean"]["perturbed"]["terminal"]["c"] == 1
            assert client.post("/api/simulate-target", json={"query": "", "extra": 1}).status_code == 422
        app.dependency_overrides[settings_dependency] = lambda: Settings(demo_enabled=False)
        assert TestClient(app).post("/api/simulate-target", json={"query": demo.DEMO_QUERY, "demo": True}).status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_real_snapshot_unreviewed_result_and_no_provider_fallback(data):
    snap, _, _ = data
    service = SimulationService(Settings(), demo.DemoParser(), demo.DemoScientist())
    result = asyncio.run(service.run(SimulateTargetRequest(query=demo.DEMO_QUERY), snap))
    assert result.analysis.baseline.category == "insufficient_evidence"
    assert result.synthesis_status == "not_requested"


def test_indra_adapter_preserves_hash_and_unknown_belief():
    result = adapter.statement_refs_from_indra([{"matches_hash": -123, "type": "Activation"}])
    assert result[0].statement_hash == "-123" and result[0].belief is None
    with pytest.raises(adapter.ManifestError):
        adapter.statement_refs_from_indra([{"type": "Activation"}])


def test_real_pybel_export_preserves_states_citations_and_parallel_claims(data):
    from nucleolis.analysis import bel_adapter
    if not bel_adapter.available():
        pytest.skip("optional PyBEL import is unavailable")
    snap, review, _ = data
    graph = adapter.adapt(snap, review, "DEMO:A", "DEMO:C")
    # Test-only PMIDs validate representation, never published as real evidence.
    for i, row in enumerate(graph.evidence):
        row.publication_id = f"PMID:{i + 1}"
    edge = graph.links[0].model_copy(deep=True, update={"id": "opposite", "sign": -1})
    graph.links.append(edge)
    graph.mappings[edge.id] = graph.mappings["demo_ab"]
    bel = bel_adapter.to_bel(graph, snap.entities)
    assert bel.number_of_nodes() == 3 and bel.number_of_edges() == 3
    edges = [attrs for _, _, attrs in bel.edges(data=True)]
    assert {e["relation"] for e in edges} == {"increases", "decreases"}
    assert all(e["target_modifier"]["modifier"] == "Activity" for e in edges)
    assert all(e["citation"] and e["evidence"] and e["annotations"] for e in edges)


def test_provider_settings_read_quotes_and_process_override(tmp_path, monkeypatch):
    from nucleolis import config
    path = tmp_path / ".env"
    path.write_text('export NEBIUS_MODEL="fixture-model"\nNEBIUS_API_KEY=\'test-only\'\n', encoding="utf-8")
    assert config._parse_env_file(path) == {"NEBIUS_MODEL": "fixture-model", "NEBIUS_API_KEY": "test-only"}
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("NEBIUS_MODEL", "process-model")
    config.env.cache_clear()
    try:
        assert Settings.from_env().nebius_model == "process-model"
    finally:
        config.env.cache_clear()


def test_boolean_gate_never_substitutes_signed_analysis(data):
    snap, review, model = data
    service = SimulationService(Settings(), demo.DemoParser(), demo.DemoScientist())
    request = SimulateTargetRequest(query=demo.DEMO_QUERY, demo=True, context_id="demo_context",
                                   method="illustrative_boolean", boolean_model_id="wrong-model")
    result = asyncio.run(service.run(request, snap, review, model))
    assert result.status == "model_not_ready" and result.analysis is None and result.synthesis is None


def test_completed_endpoint_response_exports_resolvable_references(data):
    snap, review, model = data
    service = SimulationService(Settings(), demo.DemoParser(), demo.DemoScientist())
    request = SimulateTargetRequest(query=demo.DEMO_QUERY, demo=True, context_id="demo_context",
                                   exclude_publication_ids=["DEMO-PAPER:demo_bc"])
    result = asyncio.run(service.run(request, snap, review, model))
    assert result.analysis.exclusion_effect == "sole_support_lost"
    assert result.analysis.after_exclusion.category == "insufficient_evidence"
    assert any(not link.eligible for link in result.links)
    assert result.evidence_assessment.distinct_publication_count == 1
    SimulateTargetResponse.model_validate_json(result.model_dump_json())


def test_exploratory_mode_uses_unreviewed_evidence_and_labels_it(data):
    snap, _, _ = data
    graph = adapter.adapt(snap, None, "DEMO:A", "DEMO:C", exploratory=True)
    assert {link.id for link in graph.links} == {"demo_ab", "demo_bc"}
    assert all(e.review_status == "unreviewed" for e in graph.evidence)
    assert graph.warnings[0].startswith("EXPLORATORY MODE")
    assert "2 of 2 claims lack an INDRA belief score." in graph.warnings
    assert confidence.assess(graph).reviewed_evidence_count == 0


def test_exploratory_mode_maps_statement_belief_to_links(data):
    snap, _, _ = data
    snap.claims["demo_ab"].update(belief=0.7, source_statement_hash="123")
    link = next(l for l in adapter.adapt(snap, None, "DEMO:A", "DEMO:C", exploratory=True).links if l.id == "demo_ab")
    assert link.belief_score == 0.7 and link.belief_method == "minimum_statement_belief"
    assert link.statement_refs[0].statement_hash == "123" and link.statement_refs[0].belief == 0.7


def test_exploratory_mode_drops_retracted_support(data):
    snap, _, _ = data
    snap.documents["DEMO-PAPER:demo_bc"]["retraction_status"] = "retracted"
    graph = adapter.adapt(snap, None, "DEMO:A", "DEMO:C", exploratory=True)
    assert [link.id for link in graph.links] == ["demo_ab"]
    assert any("dropped" in w for w in graph.warnings)


def test_service_runs_exploratory_analysis_without_manifest(data):
    snap, _, _ = data
    service = SimulationService(Settings(exploratory_enabled=True), demo.DemoParser(), demo.DemoScientist())
    result = asyncio.run(service.run(SimulateTargetRequest(query=demo.DEMO_QUERY), snap))
    assert result.analysis.baseline.category != "insufficient_evidence" and len(result.links) == 2
    states = {n.id: n.state for n in result.nodes}
    assert states["DEMO:A"] == "decreased" and states["DEMO:B"] == "decreased" and states["DEMO:C"] == "increased"
    SimulateTargetResponse.model_validate_json(result.model_dump_json())


def test_display_order_follows_support_not_belief():
    from nucleolis.schemas.simulation import SimulationLink

    def link(cid, source, target, papers, belief):
        return SimulationLink(id=cid, source=source, target=target, predicate="activates", sign=1,
                              papers=papers, belief=belief, belief_score=belief,
                              belief_method="minimum_statement_belief", statement_refs=[],
                              evidence_ids=[], publication_ids=[])

    links = [link("direct", "A", "C", 2, 0.9), link("ab", "A", "B", 10, 0.4), link("bc", "B", "C", 10, 0.4)]
    mappings = {l.id: ClaimMapping(claim_id=l.id, source_state="unspecified", target_state="unspecified",
                                   assumption="fixture") for l in links}
    graph = adapter.AnalysisGraph(["A", "B", "C"], links, [], mappings, [])
    query = GroundedQuery(source_id="A", target_id="C", intervention_direction=1,
                          source_state_id="unspecified", target_state_id="unspecified")
    result = signed_paths.analyze(graph, query, None)
    # The 10-paper route outranks the 2-paper route despite the latter's higher belief.
    assert [p.node_ids for p in result.paths] == [["A", "B", "C"], ["A", "C"]]
    assert result.paths[0].belief_score == 0.4


def test_links_and_assessment_carry_source_class(data):
    snap, _, _ = data
    snap.claims["demo_ab"]["source_counts"] = {"biogrid": 1}
    snap.claims["demo_bc"]["source_counts"] = {"reach": 3}
    graph = adapter.adapt(snap, None, "DEMO:A", "DEMO:C", exploratory=True)
    classes = {link.id: link.source_class for link in graph.links}
    assert classes == {"demo_ab": "curated_database", "demo_bc": "machine_read"}
    assessment = confidence.assess(graph)
    assert (assessment.curated_database_claims, assessment.machine_read_claims, assessment.multi_source_claims) == (1, 1, 0)
    assert any("does not separate extraction faults" in text for text in assessment.limitations)
