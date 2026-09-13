"""Publication identity: normalization and conservative family grouping.

Canonical priority: DOI, PMID, PMCID, AMASS ID, then a provisional hash of title,
year and first author. Records are grouped into one family only when they share
a strong identifier (DOI, PMID, PMCID) or an explicit family ID from the source.
A similar title never merges two records: when a merge is uncertain, they stay
separate and the family is marked unresolved.
"""
from __future__ import annotations

import hashlib
import re

_DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)


def normalize_doi(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    doi = _DOI_PREFIX.sub("", value.strip()).strip().lower()
    return doi if doi.startswith("10.") and "/" in doi else None


def normalize_pmid(value: object) -> str | None:
    if value is None:
        return None
    raw = re.sub(r"^pmid:\s*", "", str(value).strip(), flags=re.IGNORECASE)
    return (raw.lstrip("0") or None) if raw.isdigit() else None


def normalize_pmcid(value: object) -> str | None:
    if value is None:
        return None
    raw = re.sub(r"^pmcid:\s*", "", str(value).strip(), flags=re.IGNORECASE).upper()
    digits = raw.removeprefix("PMC")
    return f"PMC{digits.lstrip('0')}" if digits.isdigit() and digits.strip("0") else None


def strong_keys(record: dict) -> set[str]:
    """Every strong identifier a record carries, as namespaced keys."""
    keys = set()
    if doi := normalize_doi(record.get("doi")):
        keys.add(f"doi:{doi}")
    if pmid := normalize_pmid(record.get("pmid")):
        keys.add(f"pmid:{pmid}")
    if pmcid := normalize_pmcid(record.get("pmcid")):
        keys.add(f"pmcid:{pmcid}")
    return keys


def canonical_id(record: dict) -> str | None:
    for key in ("doi", "pmid", "pmcid"):
        normalized = {"doi": normalize_doi, "pmid": normalize_pmid, "pmcid": normalize_pmcid}[key](record.get(key))
        if normalized:
            return f"{key}:{normalized}"
    if record.get("amass_id"):
        return f"amass:{record['amass_id']}"
    title = re.sub(r"\W+", " ", str(record.get("title") or "")).strip().lower()
    if title and record.get("year") and record.get("first_author"):
        digest = hashlib.sha256(f"{title}|{record['year']}|{str(record['first_author']).lower()}".encode()).hexdigest()
        return f"provisional:{digest[:20]}"
    return None


def families(records: list[dict]) -> dict[str, str]:
    """Map each record's canonical ID to a family ID, merging only on strong evidence."""
    parent: dict[str, str] = {}

    def find(node: str) -> str:
        while parent.setdefault(node, node) != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a: str, b: str) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[max(root_a, root_b)] = min(root_a, root_b)

    ids = []
    for record in records:
        cid = canonical_id(record)
        if cid is None:
            continue
        ids.append((cid, record))
        find(cid)
        for key in strong_keys(record):
            union(cid, key)
        if record.get("publication_family_id"):
            union(cid, f"family:{record['publication_family_id']}")

    explicit: dict[str, str] = {}
    for cid, record in ids:
        if record.get("publication_family_id"):
            explicit.setdefault(find(cid), f"family:{record['publication_family_id']}")
    return {cid: explicit.get(find(cid), find(cid)) for cid, _ in ids}
