from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nucleolus.graph.queries import Snapshot, _document_link
from nucleolus.schemas.simulation import (
    ClaimMapping, EvidenceItem, ReviewManifest, SimulationLink, StatementRef,
)


class ManifestError(ValueError):
    pass


@dataclass
class AnalysisGraph:
    entity_ids: list[str]
    links: list[SimulationLink]
    evidence: list[EvidenceItem]
    mappings: dict[str, ClaimMapping]
    warnings: list[str]


def load_review(path: Path | None, snap: Snapshot) -> ReviewManifest | None:
    if path is None:
        return None
    try:
        manifest = ReviewManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ManifestError("Review manifest is missing or invalid.") from exc
    validate_review(manifest, snap)
    return manifest


def validate_review(manifest: ReviewManifest, snap: Snapshot) -> None:
    if manifest.snapshot_id != snap.id or manifest.snapshot_checksum != snap.checksum:
        raise ManifestError("Review manifest does not match the active snapshot checksum.")
    if manifest.context_id not in snap.contexts:
        raise ManifestError("Review context does not resolve in snapshot.")
    if set(manifest.selected_entity_ids) - snap.entities.keys():
        raise ManifestError("Selected entities do not resolve.")
    if any(m.claim_id not in snap.claims for m in manifest.mappings):
        raise ManifestError("Claim state mapping does not resolve.")
    statements = {s.statement_hash for s in manifest.statements}
    for review in manifest.reviews:
        evidence = snap.evidence.get(review.evidence_id)
        if evidence is None or evidence["claim_id"] != review.claim_id:
            raise ManifestError("Review evidence-to-claim reference does not resolve.")
        if set(review.statement_hashes) - statements:
            raise ManifestError("Review statement reference does not resolve.")


def adapt(snap: Snapshot, manifest: ReviewManifest | None, source: str, target: str,
          exclusions: set[str] | None = None) -> AnalysisGraph:
    """Build an isolated graph from human-approved evidence; never promote raw data."""
    exclusions = exclusions or set()
    if manifest is None:
        return AnalysisGraph(sorted({source, target}), [], [], {}, [
            "No checksum-bound review manifest is configured; unreviewed evidence is not eligible.",
            "The current snapshot has no stored INDRA belief scores.",
        ])
    validate_review(manifest, snap)
    selected = set(manifest.selected_entity_ids)
    if source not in selected or target not in selected:
        return AnalysisGraph(sorted({source, target}), [], [], {}, ["Query endpoints are outside the reviewed mechanism."])
    mappings = {m.claim_id: m for m in manifest.mappings}
    statements = {s.statement_hash: s for s in manifest.statements}
    by_claim: dict[str, list[EvidenceItem]] = {}
    excluded = 0
    for review in manifest.reviews:
        raw = snap.evidence[review.evidence_id]
        claim = snap.claims[review.claim_id]
        document = snap.documents.get(raw.get("document_id"))
        mapping = mappings.get(review.claim_id)
        valid = (review.approved and review.source_checked and review.context_compatible and review.reviewer
                 and mapping and raw.get("quote") and not raw.get("negated") and not claim.get("negated")
                 and claim.get("causal") and type(claim.get("effect_sign")) is int
                 and claim.get("effect_sign") in (-1, 1)
                 and claim.get("predicate") in {"activates", "inhibits", "increases_amount", "decreases_amount"}
                 and claim["subject_id"] in selected and claim["object_id"] in selected
                 and raw.get("context_id") == manifest.context_id and document
                 and document.get("retraction_status") != "retracted"
                 and document["id"] not in exclusions)
        if not valid:
            excluded += 1
            continue
        expected_sign = 1 if claim["predicate"] in {"activates", "increases_amount"} else -1
        if claim["effect_sign"] != expected_sign:
            raise ManifestError("Snapshot causal predicate and sign disagree.")
        by_claim.setdefault(claim["id"], []).append(EvidenceItem(
            id=raw["id"], claim_id=claim["id"], statement_hashes=review.statement_hashes,
            publication_id=document["id"], publication_url=_document_link(document),
            quote=raw["quote"], context_id=manifest.context_id,
            source_api=raw.get("source_evidence_code"),
        ))
    links, evidence = [], []
    for cid, rows in sorted(by_claim.items()):
        claim = snap.claims[cid]
        hashes = sorted({h for row in rows for h in row.statement_hashes})
        refs = [statements[h] for h in hashes]
        # A missing attribution on even one evidence row makes the aggregate incomplete.
        complete = bool(refs) and all(row.statement_hashes for row in rows) and all(s.belief is not None for s in refs)
        belief = min(s.belief for s in refs) if complete else None
        docs = sorted({row.publication_id for row in rows if row.publication_id})
        primary = [snap.documents[d].get("is_primary") for d in docs]
        links.append(SimulationLink(
            id=cid, source=claim["subject_id"], target=claim["object_id"], predicate=claim["predicate"],
            sign=claim["effect_sign"], papers=len(docs), sentences=len(rows),
            primary=sum(primary) if all(v is not None for v in primary) else None,
            belief=belief, belief_score=belief,
            belief_method="minimum_statement_belief" if complete else "unavailable",
            statement_refs=refs, evidence_ids=sorted(row.id for row in rows), publication_ids=docs,
        ))
        evidence.extend(rows)
    warnings = [f"{excluded} reviewed-manifest records were excluded by eligibility or publication selection."] if excluded else []
    if any(not row.statement_hashes for row in evidence):
        warnings.append("Some evidence lacks complete statement attribution; belief coverage may be incomplete.")
    return AnalysisGraph(sorted(selected), links, sorted(evidence, key=lambda e: e.id), mappings, warnings)


def statement_refs_from_indra(statements: list[dict]) -> list[StatementRef]:
    """Offline import of INDRA serialized Statements; unknown beliefs stay unknown."""
    refs = {}
    for statement in statements:
        hash_value = statement.get("matches_hash")
        if hash_value is None:
            raise ManifestError("Serialized INDRA statement lacks matches_hash; do not guess identity.")
        ref = StatementRef(statement_hash=str(hash_value), statement_type=statement["type"],
                           belief=statement.get("belief"))
        if ref.statement_hash in refs and refs[ref.statement_hash] != ref:
            raise ManifestError("Conflicting metadata for one INDRA statement hash.")
        refs[ref.statement_hash] = ref
    return [refs[key] for key in sorted(refs)]
