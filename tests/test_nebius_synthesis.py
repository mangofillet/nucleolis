"""Nebius synthesis provider: strict schema, one bounded repair and explicit failures, without live calls."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import AsyncOpenAI

from nucleolis.api.main import app
from nucleolis.api.research import snapshot_dependency
from nucleolis.api.simulation import settings_dependency
from nucleolis.graph.queries import Snapshot
from nucleolis.llm.claude import ClaudeScientist
from nucleolis.llm.common import ProviderError
from nucleolis.llm.nebius import NebiusScientist
from nucleolis.llm.scientist import build_scientist
from nucleolis.llm.settings import Settings
from test_contract import _snapshot_payload
from test_synthesis_citations import synthesis

VALID = synthesis().model_dump_json()


def completion(content, finish_reason="stop"):
    return lambda request: httpx.Response(200, json={
        "id": "test", "object": "chat.completion", "created": 0, "model": "test",
        "choices": [{"index": 0, "finish_reason": finish_reason,
                     "message": {"role": "assistant", "content": content}}]})


def run_draft(requests, *responses, **settings):
    def handler(request):
        requests.append(json.loads(request.content))
        return responses[len(requests) - 1](request)

    async def invoke():
        client = AsyncOpenAI(api_key="fixture", base_url="https://fixture.invalid", max_retries=0,
                             http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        scientist = NebiusScientist(Settings(**({"nebius_model": "parser-model"} | settings)), client)
        return await scientist.synthesize({"links": [], "evidence": []})
    return asyncio.run(invoke())


def test_draft_uses_strict_schema_and_falls_back_to_parser_model():
    requests = []
    result = run_draft(requests, completion(VALID))
    assert result.biological_rationale[0].claim_ids == ["clm_1"]
    body = requests[0]
    assert len(requests) == 1 and body["model"] == "parser-model"
    assert body["response_format"]["json_schema"]["strict"]
    assert body["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
    assert body["max_tokens"] == Settings().synthesis_tokens
    assert "output_config" not in body


def test_dedicated_synthesis_model_overrides_parser_model():
    requests = []
    run_draft(requests, completion(VALID), nebius_synthesis_model="synthesis-model")
    assert requests[0]["model"] == "synthesis-model"


def test_schema_failure_gets_exactly_one_repair():
    requests = []
    result = run_draft(requests, completion("{}"), completion(VALID))
    assert result.confidence_assessment == "Fixture."
    assert len(requests) == 2
    assert [m["role"] for m in requests[1]["messages"][-2:]] == ["assistant", "user"]


def test_repeated_schema_failure_is_invalid_output():
    requests = []
    with pytest.raises(ProviderError) as exc:
        run_draft(requests, completion("{}"), completion("{}"))
    assert exc.value.code == "invalid_output" and len(requests) == 2


@pytest.mark.parametrize("case,code,status", [
    ("truncated", "incomplete_output", 502), ("empty", "refusal", 502),
    ("timeout", "timeout", 504), ("http_error", "upstream_error", 502),
])
def test_provider_failures_are_explicit_and_do_not_leak_detail(case, code, status):
    def failing(request):
        if case == "timeout":
            raise httpx.ReadTimeout("fixture timeout", request=request)
        if case == "http_error":
            return httpx.Response(401, json={"error": {"message": "private provider detail"}})
        return completion(None if case == "empty" else VALID, "length" if case == "truncated" else "stop")(request)
    requests = []
    with pytest.raises(ProviderError) as exc:
        run_draft(requests, failing)
    assert (exc.value.stage, exc.value.code, exc.value.status_code) == ("synthesis", code, status)
    assert "private provider detail" not in exc.value.message
    assert len(requests) == 1


def test_missing_key_or_model_is_not_configured():
    for settings in (Settings(nebius_api_key="fixture"), Settings(nebius_model="parser-model")):
        with pytest.raises(ProviderError) as exc:
            asyncio.run(NebiusScientist(settings).synthesize({}))
        assert exc.value.code == "not_configured" and exc.value.status_code == 503


def test_nebius_is_the_default_provider_and_claude_is_opt_in():
    nebius_only = Settings(nebius_api_key="fixture", nebius_model="parser-model")
    assert isinstance(build_scientist(nebius_only), NebiusScientist)
    assert nebius_only.synthesis_configured and nebius_only.synthesis_model == "parser-model"
    claude = nebius_only.model_copy(update={"synthesis_provider": "anthropic"})
    assert isinstance(build_scientist(claude), ClaudeScientist)
    assert not claude.synthesis_configured


def test_capabilities_report_nebius_drafts_without_an_anthropic_key():
    settings = Settings(nebius_api_key="fixture", nebius_model="parser-model")
    app.dependency_overrides[snapshot_dependency] = lambda: Snapshot(_snapshot_payload(), path=None)
    app.dependency_overrides[settings_dependency] = lambda: settings
    try:
        client = TestClient(app)
        assert client.get("/api/research/capabilities").json()["research_draft_configured"]
        caps = client.get("/api/simulation-capabilities").json()
        assert caps["synthesis_configured"] and caps["synthesis_provider"] == "nebius"
        assert caps["synthesis_model"] == "parser-model"
    finally:
        app.dependency_overrides.clear()
