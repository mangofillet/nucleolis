"""Checksum-bound corroboration cache.

An external search is mutable, so a cached assessment is only reusable when
everything it depended on is unchanged: the snapshot checksum, the claim, its
sign, the context, the classifier, and the review policy. Anything else is a
miss, never a silent reuse. Writes are atomic; the serving API never mutates the
validated snapshot.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from nucleolus import config
from nucleolus.schemas.corroboration import ClaimCorroboration

CACHE_VERSION = "amass_corroboration_v1"


def cache_dir() -> Path:
    return config.data_dir() / "amass_cache"


def key(*, snapshot_checksum: str | None, claim_id: str, sign: int | None, context_id: str | None,
        classifier: str, policy: str, include_fulltext: bool) -> str:
    parts = [CACHE_VERSION, snapshot_checksum or "no_checksum", claim_id, str(sign), context_id or "no_context",
             classifier, policy, "ft" if include_fulltext else "no_ft"]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


def read(cache_key: str) -> tuple[ClaimCorroboration, str] | None:
    """The stored assessment and when it was retrieved, or None on any mismatch."""
    path = cache_dir() / f"{cache_key}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if payload.get("cache_version") != CACHE_VERSION:
        return None
    try:
        return ClaimCorroboration.model_validate(payload["corroboration"]), str(payload.get("retrieved_at") or "")
    except (KeyError, ValueError):
        return None


def write(cache_key: str, corroboration: ClaimCorroboration, retrieved_at: str) -> None:
    directory = cache_dir()
    directory.mkdir(parents=True, exist_ok=True)
    payload = {"cache_version": CACHE_VERSION, "retrieved_at": retrieved_at,
               "corroboration": corroboration.model_dump(mode="json")}
    handle, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=1)
        os.replace(temporary, directory / f"{cache_key}.json")
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
