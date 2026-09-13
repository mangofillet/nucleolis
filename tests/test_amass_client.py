"""The AMASS transport, against a mocked transport. No key, no credits, no network."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from nucleolus.pipeline.sources.amass import AmassClient, AmassError, parse_record, passage_text

KEY = "test-only-not-a-real-key"
RECORD = {"amassId": "AMBC_1", "pmid": "38360089", "doi": "10.1/A", "title": "Fixture",
          "publicationDate": "2024-08-01", "publicationTypes": ["Journal Article"], "journal": "J Fixture",
          "isRetracted": False, "citationCount": 7.0, "journalQualityJufo": 2, "hasFulltext": True,
          "abstract": "Fixture abstract sentence."}


def run(handler, method, *args, **kwargs):
    async def main():
        async with AmassClient(KEY, transport=httpx.MockTransport(handler), **kwargs) as client:
            result = await getattr(client, method)(*args)
            return result, client.calls_used
    return asyncio.run(main())


def test_bearer_header_and_lookup_serialization():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("Authorization")
        seen["path"], seen["body"] = request.url.path, request.content
        return httpx.Response(200, json={"data": [{"input": {"pmid": "38360089"}, "amassIds": ["AMBC_1"]}]})

    rows, calls = run(handler, "lookup", [{"pmid": "38360089"}, {"doi": "10.1/A"}, {}])
    assert seen["auth"] == f"Bearer {KEY}" and calls == 1
    assert seen["path"].endswith("/cores/biomedcore/records/lookup")
    assert b'"items"' in seen["body"] and b'"doi"' in seen["body"]
    assert rows[0]["amassIds"] == ["AMBC_1"]


def test_search_limit_is_clamped_and_fulltext_is_opt_in():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"data": [RECORD]})

    rows, _ = run(handler, "search", "\"TBK1\" activates \"OPTN\"", 5000)
    assert "limit=300" in seen["url"] and "include=fulltext" not in seen["url"]
    assert rows[0]["amassId"] == "AMBC_1"


@pytest.mark.parametrize("status,code", [(400, "bad_request"), (401, "unauthorized"), (403, "forbidden"),
                                         (404, "not_found"), (500, "upstream_error")])
def test_http_failures_are_sanitized(status, code):
    with pytest.raises(AmassError) as raised:
        run(lambda request: httpx.Response(status, json={"error": {"status": status, "message": "upstream detail"}}),
            "record", "AMBC_1")
    assert raised.value.code == code
    # Neither the key nor the upstream body may reach the message.
    assert KEY not in str(raised.value) and "upstream detail" not in str(raised.value)


@pytest.mark.parametrize("case", ["malformed", "no_wrapper", "oversized", "timeout", "connection"])
def test_transport_faults_are_explicit(case):
    def handler(request):
        if case == "timeout":
            raise httpx.ReadTimeout("fixture", request=request)
        if case == "connection":
            raise httpx.ConnectError("fixture", request=request)
        if case == "malformed":
            return httpx.Response(200, content=b"not json")
        if case == "no_wrapper":
            return httpx.Response(200, json=[RECORD])
        return httpx.Response(200, json={"data": [RECORD | {"abstract": "x" * 5000}]})

    kwargs = {"max_response_bytes": 500} if case == "oversized" else {}
    with pytest.raises(AmassError) as raised:
        run(handler, "record", "AMBC_1", **kwargs)
    assert raised.value.code in {"malformed", "schema_drift", "oversized", "timeout", "connection"}


def test_rate_limit_retries_once_within_the_deadline():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, json={"error": {"status": 429, "code": "TOO_MANY_REQUESTS",
                                                        "message": "slow down", "retryAfter": 0}})
        return httpx.Response(200, json={"data": RECORD})

    record, used = run(handler, "record", "AMBC_1")
    assert record["amassId"] == "AMBC_1" and used == 2


def test_persistent_rate_limit_stops():
    body = {"error": {"status": 429, "code": "TOO_MANY_REQUESTS", "message": "slow", "retryAfter": 0}}
    with pytest.raises(AmassError) as raised:
        run(lambda request: httpx.Response(429, json=body), "record", "AMBC_1")
    assert raised.value.code == "rate_limited"


def test_call_budget_is_enforced():
    async def main():
        async with AmassClient(KEY, transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"data": RECORD})), max_calls=1) as client:
            await client.record("AMBC_1")
            with pytest.raises(AmassError) as raised:
                await client.record("AMBC_2")
            assert raised.value.code == "call_budget_exhausted"
            assert client.calls_used == 1
    asyncio.run(main())


def test_missing_key_is_refused_before_any_call():
    with pytest.raises(AmassError) as raised:
        AmassClient("")
    assert raised.value.code == "not_configured"


def test_parse_record_tolerates_optional_fields():
    full = parse_record(RECORD)
    assert full.citation_count == 7 and full.journal_quality_jufo == 2 and full.is_retracted is False
    sparse = parse_record({"amassId": "AMBC_2", "citationCount": None, "journalQualityJufo": 9, "isRetracted": None})
    assert sparse.pmid is None and sparse.citation_count is None and sparse.journal_quality_jufo is None
    assert sparse.is_retracted is None and sparse.publication_types == []
    assert parse_record({"pmid": "1"}) is None and parse_record("not a record") is None


def test_passage_text_prefers_the_abstract():
    assert passage_text(RECORD) == ("Fixture abstract sentence.", "abstract")
    assert passage_text({"fulltext": "Body text."}) == ("Body text.", "fulltext")
    assert passage_text({"abstract": "   "}) is None
