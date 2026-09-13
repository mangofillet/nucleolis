"""Exercise actual SDK serialization with an in-memory HTTP transport."""
import asyncio
import json

import httpx
import pytest
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from nucleolus.analysis import demo, grounding
from nucleolus.llm.claude import ClaudeScientist
from nucleolus.llm.common import ProviderError
from nucleolus.llm.nebius import NebiusParser
from nucleolus.llm.settings import Settings
from nucleolus.schemas.simulation import ClaudeSynthesis, NarrativeClaim, SimulateTargetRequest
from nucleolus.services.simulate_target import SimulationService, evidence_bundle, validate_citations


def parsed_json():
    return asyncio.run(demo.DemoParser().parse(demo.DEMO_QUERY, [])).model_dump_json()


def nebius_response(content, finish="stop", refusal=None):
    return {"id": "test", "object": "chat.completion", "created": 0, "model": "test-model",
            "choices": [{"index": 0, "finish_reason": finish,
                         "message": {"role": "assistant", "content": content, "refusal": refusal}}]}


def test_nebius_actual_sdk_schema_and_repair():
    seen = []
    valid = parsed_json()
    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        assert request.url.path == "/v1/chat/completions"
        assert body["response_format"]["json_schema"]["strict"] is True
        return httpx.Response(200, json=nebius_response("{}" if len(seen) == 1 else valid))
    async def run():
        async with AsyncOpenAI(api_key="test-only", base_url="https://fixture.invalid/v1/", max_retries=0,
                               http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as client:
            parser = NebiusParser(Settings(nebius_model="test-model"), client)
            return await parser.parse(demo.DEMO_QUERY, grounding.catalog(demo.fixture()[0]))
    result = asyncio.run(run())
    assert result.source_entity.candidate_id == "DEMO:A"
    assert len(seen) == 2


@pytest.mark.parametrize("case", ["malformed", "refusal", "truncated", "unknown_id", "http_error", "timeout"])
def test_nebius_failures_are_explicit_and_bounded(case):
    valid = parsed_json()
    calls = []
    def handler(request):
        calls.append(1)
        if case == "timeout":
            raise httpx.ReadTimeout("fixture timeout", request=request)
        if case == "http_error":
            return httpx.Response(401, json={"error": {"message": "invalid key", "type": "authentication_error"}})
        content = "{}" if case == "malformed" else valid.replace("DEMO:A", "INVALID:A") if case == "unknown_id" else valid
        return httpx.Response(200, json=nebius_response(content, "length" if case == "truncated" else "stop",
                                                       "refused" if case == "refusal" else None))
    async def run():
        async with AsyncOpenAI(api_key="test-only", max_retries=0,
                               http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as client:
            return await NebiusParser(Settings(nebius_model="fixture"), client).parse(demo.DEMO_QUERY, grounding.catalog(demo.fixture()[0]))
    with pytest.raises(ProviderError):
        asyncio.run(run())
    assert len(calls) <= 2


@pytest.mark.parametrize("case", ["valid", "malformed", "truncated", "refusal", "http_error", "timeout"])
def test_claude_actual_sdk_schema_and_failures(case):
    draft = asyncio.run(demo.DemoScientist().synthesize({})).model_dump_json()
    def handler(request):
        body = json.loads(request.content)
        assert body["output_config"]["format"]["type"] == "json_schema"
        assert body["output_config"]["effort"] == "medium"
        if case == "timeout":
            raise httpx.ReadTimeout("fixture timeout", request=request)
        if case == "http_error":
            return httpx.Response(500, json={"type": "error", "error": {"type": "api_error", "message": "fixture"}})
        return httpx.Response(200, json={"id": "msg_fixture", "type": "message", "role": "assistant", "model": "fixture",
            "content": [{"type": "text", "text": "{}" if case == "malformed" else draft}],
            "stop_reason": "max_tokens" if case == "truncated" else "refusal" if case == "refusal" else "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1}})
    async def run():
        async with AsyncAnthropic(api_key="test-only", max_retries=0,
                                  http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as client:
            return await ClaudeScientist(Settings(), client).synthesize({})
    if case == "valid":
        assert asyncio.run(run()).validation_protocol is None
    else:
        with pytest.raises(ProviderError):
            asyncio.run(run())


def test_citation_identity_and_relationship_validation():
    snap, review, model = demo.fixture()
    service = SimulationService(Settings(), demo.DemoParser(), demo.DemoScientist())
    response = asyncio.run(service.run(SimulateTargetRequest(query=demo.DEMO_QUERY, context_id="demo_context", demo=True), snap, review, model))
    bundle, _ = evidence_bundle(response)
    draft = response.synthesis.model_copy(deep=True)
    draft.biological_rationale = [NarrativeClaim(text="Fixture evidence assertion.", basis="evidence",
                                               claim_ids=["demo_ab"], evidence_ids=["e_demo_ab"], path_ids=[], rule_ids=[])]
    validate_citations(draft, bundle)
    draft.biological_rationale[0].evidence_ids = ["e_demo_bc"]
    with pytest.raises(ValueError):
        validate_citations(draft, bundle)
    draft.biological_rationale[0].evidence_ids = ["INVENTED:PMID"]
    with pytest.raises(ValueError):
        validate_citations(draft, bundle)


def test_timeout_after_analysis_preserves_result():
    class SlowScientist:
        model = "slow-test"
        async def synthesize(self, bundle):
            await asyncio.sleep(1)
    snap, review, model = demo.fixture()
    service = SimulationService(Settings(timeout=0.05, total_timeout=0.1), demo.DemoParser(), SlowScientist())
    result = asyncio.run(service.run(SimulateTargetRequest(query=demo.DEMO_QUERY, context_id="demo_context", demo=True), snap, review, model))
    assert result.status == "partial" and result.analysis.baseline.total_paths == 1
    assert result.errors[0].code == "timeout"
