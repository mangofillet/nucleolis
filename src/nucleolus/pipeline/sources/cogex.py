"""INDRA CoGEx adapter.

Verified live 2026-09-12 against https://discovery.indra.bio/api :
  - indra_subnetwork_meta returned 833 relations for 18 genes in 0.59s
  - get_evidences_for_stmt_hash requires stmt_hash as a STRING; an integer
    returns HTTP 415 with {"message": "stmt_hash must be a string or list of strings"}
  - evidence records carry: text, pmid, text_refs{PMID,PMCID,DOI}, source_api,
    source_hash, epistemics

A successful public probe does not establish bulk reuse rights (EXECUTION_PLAN.md s10).
"""
from __future__ import annotations

import time
from typing import Any

import httpx

# Row layout returned by indra_subnetwork_meta
REL_SOURCE, REL_TARGET, REL_TYPE, REL_HASH, REL_SOURCE_COUNTS = range(5)


class CogexError(RuntimeError):
    pass


class CogexClient:
    def __init__(
        self,
        base_url: str = "https://discovery.indra.bio/api",
        rate_limit_rps: float = 3.0,
        timeout: float = 90.0,
        max_retries: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._min_interval = 1.0 / rate_limit_rps if rate_limit_rps else 0.0
        self._last_call = 0.0
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": "nucleolus/0.1"})
        self.max_retries = max_retries
        self.call_log: list[dict[str, Any]] = []

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "CogexClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call = time.monotonic()

    def _post(self, endpoint: str, payload: dict) -> Any:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            self._throttle()
            started = time.monotonic()
            try:
                response = self._client.post(url, json=payload)
            except httpx.HTTPError as exc:
                last_error = exc
                time.sleep(2**attempt)
                continue
            duration = time.monotonic() - started
            self.call_log.append(
                {
                    "endpoint": endpoint,
                    "status": response.status_code,
                    "seconds": round(duration, 3),
                    "bytes": len(response.content),
                    "attempt": attempt + 1,
                }
            )
            if response.status_code == 200:
                return response.json()
            # 4xx other than 429 will not improve on retry
            if 400 <= response.status_code < 500 and response.status_code != 429:
                raise CogexError(f"{endpoint} -> HTTP {response.status_code}: {response.text[:300]}")
            last_error = CogexError(f"{endpoint} -> HTTP {response.status_code}")
            time.sleep(2**attempt)
        raise CogexError(f"{endpoint} failed after {self.max_retries} attempts: {last_error}")

    # -- queries -----------------------------------------------------------

    def genes_for_disease(self, namespace: str, identifier: str) -> list[dict]:
        return self._post("get_genes_for_disease", {"disease": [namespace, identifier]})

    def subnetwork_meta(self, nodes: list[tuple[str, str]]) -> list[list]:
        """Relations induced among `nodes`. Returns rows of
        [source_curie, target_curie, stmt_type, stmt_hash, source_counts]."""
        return self._post("indra_subnetwork_meta", {"nodes": [list(n) for n in nodes]})

    def evidences_for_hash(self, stmt_hash: int | str) -> list[dict]:
        """stmt_hash MUST be sent as a string - an int returns HTTP 415."""
        return self._post("get_evidences_for_stmt_hash", {"stmt_hash": str(stmt_hash)})

    def evidences_for_hashes(self, stmt_hashes: list[int | str]) -> dict[str, list[dict]]:
        """Batch variant. Falls back to per-hash calls if the batch shape is rejected."""
        payload = {"stmt_hashes": [str(h) for h in stmt_hashes]}
        try:
            result = self._post("get_evidences_for_stmt_hashes", payload)
            if isinstance(result, dict):
                return {str(k): v for k, v in result.items()}
            raise CogexError("unexpected batch response shape")
        except CogexError:
            return {str(h): self.evidences_for_hash(h) for h in stmt_hashes}
