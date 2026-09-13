"""AMASS BiomedCore adapter.

Verified against the live API on 2026-09-12 and its public OpenAPI spec
(/api/doc/openapi.json, 23 endpoints):
  - every response wraps its payload as {"data": ...}
  - POST records/lookup takes {"items": [{"pmid"}|{"doi"}]} and returns, per
    item, {"input", "amassIds", "error"} - identifiers only, so metadata needs a
    GET per record
  - GET records?query= returns ranked BiomedCoreRecord objects, limit 1-300
  - `fulltext` is only returned when requested with include=fulltext
  - HTTP 429 carries `retryAfter` (seconds) in the JSON error body; no
    Retry-After header is declared
  - cost is 1 credit per call, independent of batch size

Reuse and redistribution rights are NOT established. The adapter is disabled by
default, tests use mocked transports, and nothing it returns is committed.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from nucleolis.schemas.corroboration import AmassDocumentMetadata

BASE_URL = "https://api.amass.tech/api/v1"
MAX_RETRY_WAIT_SECONDS = 30.0
SAFE_CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found", 429: "rate_limited"}


class AmassError(RuntimeError):
    """A sanitized failure. Never carries the key or a raw upstream body."""

    def __init__(self, code: str, message: str, status: int | None = None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _retry_after(response: httpx.Response) -> float | None:
    try:
        value = response.json()["error"]["retryAfter"]
    except (ValueError, KeyError, TypeError):
        return None
    return float(value) if isinstance(value, (int, float)) and value >= 0 else None


class AmassClient:
    def __init__(self, api_key: str, base_url: str = BASE_URL, *, timeout: float = 15.0, max_calls: int = 6,
                 max_response_bytes: int = 2_000_000, deadline_seconds: float | None = None,
                 transport: httpx.AsyncBaseTransport | None = None):
        if not api_key:
            raise AmassError("not_configured", "AMASS is not configured.")
        self.base_url = base_url.rstrip("/")
        self.max_calls, self.max_response_bytes = max_calls, max_response_bytes
        self.calls_used = 0
        self._deadline = time.monotonic() + deadline_seconds if deadline_seconds else None
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport, headers={
            "Authorization": f"Bearer {api_key}", "User-Agent": "nucleolis/0.1"})

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "AmassClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    def _remaining(self) -> float | None:
        return None if self._deadline is None else self._deadline - time.monotonic()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        for attempt in range(2):
            if self.calls_used >= self.max_calls:
                raise AmassError("call_budget_exhausted", f"AMASS call budget of {self.max_calls} reached.")
            remaining = self._remaining()
            if remaining is not None and remaining <= 0:
                raise AmassError("deadline", "AMASS stage exceeded its deadline.")
            self.calls_used += 1
            try:
                response = await self._client.request(method, f"{self.base_url}/{path}", **kwargs)
            except httpx.TimeoutException as exc:
                raise AmassError("timeout", "AMASS request timed out.") from exc
            except httpx.HTTPError as exc:
                raise AmassError("connection", "AMASS could not be reached.") from exc
            if len(response.content) > self.max_response_bytes:
                raise AmassError("oversized", "AMASS response exceeded the size bound.", response.status_code)
            if response.status_code == 429 and attempt == 0:
                wait = _retry_after(response)
                remaining = self._remaining()
                # Honour retryAfter only when it fits inside the request deadline.
                if wait is not None and wait <= MAX_RETRY_WAIT_SECONDS and (remaining is None or wait < remaining):
                    await asyncio.sleep(wait)
                    continue
            if response.status_code != 200:
                code = SAFE_CODES.get(response.status_code, "upstream_error")
                raise AmassError(code, f"AMASS returned HTTP {response.status_code}.", response.status_code)
            try:
                payload = response.json()
            except ValueError as exc:
                raise AmassError("malformed", "AMASS returned a non-JSON body.", 200) from exc
            if not isinstance(payload, dict) or "data" not in payload:
                raise AmassError("schema_drift", "AMASS response lacked the documented data wrapper.", 200)
            return payload["data"]
        raise AmassError("rate_limited", "AMASS rate limit persisted.", 429)

    async def lookup(self, items: list[dict]) -> list[dict]:
        """Resolve PMIDs/DOIs to AMASS IDs. One call, however many items."""
        clean = [{"pmid": str(i["pmid"])} if i.get("pmid") else {"doi": str(i["doi"])}
                 for i in items if i.get("pmid") or i.get("doi")]
        if not clean:
            return []
        data = await self._request("POST", "cores/biomedcore/records/lookup", json={"items": clean})
        if not isinstance(data, list):
            raise AmassError("schema_drift", "AMASS lookup did not return a list.", 200)
        return [row for row in data if isinstance(row, dict)]

    async def record(self, amass_id: str, include_fulltext: bool = False) -> dict:
        params = {"include": ["fulltext"]} if include_fulltext else None
        data = await self._request("GET", f"cores/biomedcore/records/{amass_id}", params=params)
        if not isinstance(data, dict):
            raise AmassError("schema_drift", "AMASS record was not an object.", 200)
        return data

    async def search(self, query: str, limit: int = 20, include_fulltext: bool = False) -> list[dict]:
        params: dict[str, Any] = {"query": query, "limit": max(1, min(int(limit), 300))}
        if include_fulltext:
            params["include"] = ["fulltext"]
        data = await self._request("GET", "cores/biomedcore/records", params=params)
        if not isinstance(data, list):
            raise AmassError("schema_drift", "AMASS search did not return a list.", 200)
        return [row for row in data if isinstance(row, dict)]


def parse_record(raw: dict) -> AmassDocumentMetadata | None:
    """Map one BiomedCoreRecord. Returns None for a record without an AMASS ID."""
    if not isinstance(raw, dict) or not raw.get("amassId"):
        return None

    def text(key: str) -> str | None:
        value = raw.get(key)
        return value.strip() or None if isinstance(value, str) else None

    def strings(key: str) -> list[str]:
        value = raw.get(key)
        return [v for v in value if isinstance(v, str)][:40] if isinstance(value, list) else []

    citations = raw.get("citationCount")
    jufo = raw.get("journalQualityJufo")
    retracted = raw.get("isRetracted")
    fulltext = raw.get("hasFulltext")
    return AmassDocumentMetadata(
        amass_id=str(raw["amassId"]), pmid=text("pmid"), pmcid=text("pmcid"), doi=text("doi"),
        title=text("title"), publication_date=text("publicationDate"), publication_types=strings("publicationTypes"),
        journal=text("journal"),
        is_retracted=retracted if isinstance(retracted, bool) else None,
        has_fulltext=fulltext if isinstance(fulltext, bool) else None,
        citation_count=int(citations) if isinstance(citations, (int, float)) and citations >= 0 else None,
        journal_quality_jufo=int(jufo) if isinstance(jufo, (int, float)) and 0 <= jufo <= 3 else None,
        publication_family_id=text("publicationFamilyId"),
    )


def passage_text(raw: dict) -> tuple[str, str] | None:
    """The text a classifier may read, and where it came from. Abstract before full text."""
    for key, location in (("abstract", "abstract"), ("fulltext", "fulltext")):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip(), location
    return None
