"""Snapshot stage: normalized tables -> a validated, versioned, immutable snapshot.

EXECUTION_PLAN.md s2 requires one offline writer: snapshots are built separately
from the API's active database, validated, and only then served. A snapshot that
fails validation is never written to the serving path.

Validation is structural, not scientific. It proves the graph is internally
consistent and that every citation resolves. It does NOT prove a claim is true.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys

from nucleolus import config

SCHEMA_VERSION = 1


class ValidationError(Exception):
    pass


def validate(tables) -> list[str]:
    """Return a list of structural problems. Empty list means the snapshot is valid."""
    problems = []
    vocabulary = set(config.predicates()["vocabulary"])

    entities = {e["id"]: e for e in tables["entities"]}
    contexts = {c["id"]: c for c in tables["contexts"]}
    claims = {c["id"]: c for c in tables["claims"]}
    documents = {d["id"]: d for d in tables["documents"]}
    evidence = {e["id"]: e for e in tables["evidence"]}

    def check_unique(rows, label):
        ids = [r["id"] for r in rows]
        if len(ids) != len(set(ids)):
            problems.append(label + ": duplicate IDs present")

    for rows, label in (
        (tables["entities"], "entities"),
        (tables["contexts"], "contexts"),
        (tables["claims"], "claims"),
        (tables["documents"], "documents"),
        (tables["evidence"], "evidence"),
        (tables["provenance"], "provenance"),
    ):
        check_unique(rows, label)

    for claim in claims.values():
        if claim["subject_id"] not in entities:
            problems.append("claim " + claim["id"] + ": subject not in entities")
        if claim["object_id"] not in entities:
            problems.append("claim " + claim["id"] + ": object not in entities")
        if claim["context_id"] not in contexts:
            problems.append("claim " + claim["id"] + ": context not in contexts")
        if claim["predicate"] not in vocabulary:
            problems.append("claim " + claim["id"] + ": predicate outside vocabulary")
        if claim["effect_sign"] not in (1, -1, None):
            problems.append("claim " + claim["id"] + ": effect_sign not in {1,-1,null}")
        # A non-causal predicate must never carry a sign.
        if not claim.get("causal") and claim["effect_sign"] is not None:
            problems.append(
                "claim " + claim["id"] + ": non-causal predicate '"
                + claim["predicate"] + "' carries a sign"
            )
        for evidence_id in claim["evidence_ids"]:
            if evidence_id not in evidence:
                problems.append("claim " + claim["id"] + ": dangling evidence " + evidence_id)

    for row in evidence.values():
        if row["claim_id"] not in claims:
            problems.append("evidence " + row["id"] + ": claim does not resolve")
        if row["document_id"] is not None and row["document_id"] not in documents:
            problems.append("evidence " + row["id"] + ": document does not resolve")
        if row["context_id"] not in contexts:
            problems.append("evidence " + row["id"] + ": context does not resolve")

    for row in tables["provenance"]:
        if row["claim_id"] not in claims:
            problems.append("provenance " + row["id"] + ": claim does not resolve")
        if row["evidence_id"] is not None and row["evidence_id"] not in evidence:
            problems.append("provenance " + row["id"] + ": evidence does not resolve")

    # A publication date must never be filled in from the retrieval date.
    for document in documents.values():
        if document["publication_date"] is None and document["date_precision"] != "unknown":
            problems.append(
                "document " + document["id"] + ": missing date not marked unknown"
            )

    return problems


def build(run_id=None, label=None):
    data_root = config.data_dir()
    if run_id is None:
        latest = data_root / "normalized" / "LATEST"
        if not latest.exists():
            raise SystemExit("[build] no normalized run - run normalize first")
        run_id = latest.read_text(encoding="utf-8").strip()

    tables_path = data_root / "normalized" / run_id / "tables.json"
    tables = json.loads(tables_path.read_text(encoding="utf-8"))

    print("[build] validating " + str(tables_path) + " ...")
    problems = validate(tables)
    if problems:
        print("[build] VALIDATION FAILED - " + str(len(problems)) + " problems:")
        for problem in problems[:25]:
            print("        - " + problem)
        if len(problems) > 25:
            print("        ... and " + str(len(problems) - 25) + " more")
        raise SystemExit(1)
    print("[build] validation passed")

    created_at = dt.datetime.now(dt.timezone.utc)
    snapshot_id = label or ("snap_" + created_at.strftime("%Y%m%dT%H%M%SZ"))

    raw_manifest_path = data_root / "raw" / run_id / "manifest.json"
    raw_manifest = json.loads(raw_manifest_path.read_text(encoding="utf-8"))

    payload = {
        "id": snapshot_id,
        "schema_version": SCHEMA_VERSION,
        "created_at": created_at.isoformat(),
        "source_run_id": run_id,
        "manifest_ref": "data/raw/" + run_id + "/manifest.json",
        "query": raw_manifest.get("query"),
        "seed_verification": raw_manifest.get("seed_verification"),
        "license_note": raw_manifest.get("license_note"),
        "entities": tables["entities"],
        "contexts": tables["contexts"],
        "claims": tables["claims"],
        "documents": tables["documents"],
        "evidence": tables["evidence"],
        "provenance": tables["provenance"],
        "coverage": {
            "entities": len(tables["entities"]),
            "claims": len(tables["claims"]),
            "claims_signed": tables["stats"]["claims_signed"],
            "claims_unsigned": tables["stats"]["claims_unsigned"],
            "documents": len(tables["documents"]),
            "evidence": len(tables["evidence"]),
            "relations_unmapped": tables["stats"]["relations_unmapped"],
            "evidence_negated": tables["stats"]["evidence_negated"],
            "evidence_with_quote": tables["stats"]["evidence_with_quote"],
            "evidence_with_structured_context": tables["stats"]["evidence_with_context"],
            "documents_without_publication_date": tables["stats"]["documents_without_date"],
            "documents_dated": tables["stats"].get("documents_dated", 0),
            "documents_primary": tables["stats"].get("documents_primary", 0),
            "documents_secondary": tables["stats"].get("documents_secondary", 0),
            "documents_retracted": tables["stats"].get("documents_retracted", 0),
            "claims_with_belief": tables["stats"].get("claims_with_belief", 0),
            "belief_min": tables["stats"].get("belief_min"),
            "belief_median": tables["stats"].get("belief_median"),
            "belief_max": tables["stats"].get("belief_max"),
            "claims_with_obj_activity": tables["stats"].get("claims_with_obj_activity", 0),
        },
        "enrichment": tables.get("enrichment"),
        "limitations": [
            "Claims are automatically extracted by upstream INDRA readers and "
            "databases. None has been reviewed by a domain scientist.",
            "Publication dates come from PubMed and keep their stated precision "
            "(year, month or day). Undated documents are excluded from date "
            "filters rather than assigned a guess.",
            "Structured experimental context (species, cell type, dose) is largely "
            "absent, so species/context separation is not yet enforced.",
            "Support counts are distinct publications, not independent studies.",
            "INDRA belief is a statement assembly score, never a treatment "
            "probability. Compounding it across hops degrades quickly, which is "
            "why signed inference is capped at two hops.",
        ],
    }

    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["checksum"] = "sha256:" + hashlib.sha256(body).hexdigest()

    snapshots_dir = data_root / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    out_path = snapshots_dir / (snapshot_id + ".json")
    out_path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    (snapshots_dir / "CURRENT").write_text(snapshot_id, encoding="utf-8")

    coverage = payload["coverage"]
    print("[build] snapshot " + snapshot_id)
    print("[build]   entities " + str(coverage["entities"])
          + " | claims " + str(coverage["claims"])
          + " (signed " + str(coverage["claims_signed"]) + ")"
          + " | documents " + str(coverage["documents"])
          + " | evidence " + str(coverage["evidence"]))
    print("[build]   checksum " + payload["checksum"][:23] + "...")
    print("[build]   written to " + str(out_path))
    return out_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build a validated snapshot")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--label", default=None, help="snapshot id, e.g. demo_frozen")
    args = parser.parse_args(argv)
    build(args.run_id, args.label)
    return 0


if __name__ == "__main__":
    sys.exit(main())
