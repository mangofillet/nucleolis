"""Normalization stage: raw CoGEx cache -> the EXECUTION_PLAN.md s4 data contract.

Produces entities, contexts, claims, documents, evidence and provenance tables
with IDs that are stable across reruns (content hashes, never random UUIDs), so
ingestion is idempotent.

Rules enforced here, all from EXECUTION_PLAN.md s4:
  - Phosphorylation is a mechanism, not activation. Binding and association have
    no default causal sign. effect_sign stays null for those predicates.
  - Negation is separate from inhibition. Negated evidence is marked and does not
    count as support; it never flips a sign.
  - A paper repeated across upstream resources counts as ONE supporting document,
    with multiple provenance records.
  - Unknown context and unknown experimental basis stay unknown.
  - Publication dates are never substituted with retrieval dates.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import sys

import httpx

from nucleolis import config
from nucleolis.pipeline.sources.cogex import (
    REL_HASH,
    REL_SOURCE,
    REL_SOURCE_COUNTS,
    REL_TARGET,
    REL_TYPE,
)

SCHEMA_VERSION = 1
HGNC_BY_ID = "https://rest.genenames.org/fetch/hgnc_id/HGNC:{accession}"


def _hash(*parts) -> str:
    joined = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]


def parse_curie(curie: str):
    """'hgnc:11741' -> ('HGNC', '11741'). Namespace is upper-cased for stability."""
    if ":" not in curie:
        return "UNKNOWN", curie
    namespace, accession = curie.split(":", 1)
    return namespace.upper(), accession


def entity_id(namespace: str, accession: str) -> str:
    return namespace + ":" + accession


# ---------------------------------------------------------------------------
# entity names
# ---------------------------------------------------------------------------

def resolve_entity_names(curies, cache_path):
    """Look up preferred names for HGNC entities, cached on disk between runs."""
    cache = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))

    missing = [c for c in curies if c not in cache]
    if missing:
        print("[normalize] resolving " + str(len(missing)) + " entity names via HGNC ...")
        with httpx.Client(timeout=30.0, headers={"Accept": "application/json"}) as client:
            for index, curie in enumerate(missing, start=1):
                namespace, accession = parse_curie(curie)
                if namespace != "HGNC":
                    cache[curie] = {"preferred_name": None, "entity_type": "unknown"}
                    continue
                try:
                    response = client.get(HGNC_BY_ID.format(accession=accession))
                    docs = response.json().get("response", {}).get("docs", [])
                except Exception:
                    docs = []
                if docs:
                    cache[curie] = {
                        "preferred_name": docs[0].get("symbol"),
                        "long_name": docs[0].get("name"),
                        "entity_type": "gene_protein",
                        "taxon_id": 9606,
                    }
                else:
                    # Unresolved stays unresolved - never invent a name.
                    cache[curie] = {"preferred_name": None, "entity_type": "unresolved"}
                if index % 25 == 0:
                    print("           " + str(index) + "/" + str(len(missing)))
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return cache


# ---------------------------------------------------------------------------
# context extraction
# ---------------------------------------------------------------------------

def extract_context(evidence_record):
    """Pull whatever structured biological context the source actually provides.

    Returns a dict of context fields. Absent fields stay None - they are NOT
    defaulted to human, and NOT inferred from the sentence.
    """
    context = evidence_record.get("context") or {}
    if not isinstance(context, dict):
        context = {}

    def ref_name(key):
        value = context.get(key)
        if isinstance(value, dict):
            return value.get("name")
        return value if isinstance(value, str) else None

    taxon = None
    species = context.get("species")
    if isinstance(species, dict):
        db_refs = species.get("db_refs") or {}
        taxon = db_refs.get("TAXONOMY") or db_refs.get("taxonomy")

    return {
        "taxon_id": taxon,
        "tissue": ref_name("organ"),
        "cell_type": ref_name("cell_type"),
        "cell_line": ref_name("cell_line"),
        "disease": ref_name("disease"),
        "location": ref_name("location"),
    }


def context_key(fields):
    if not any(fields.values()):
        return "ctx_unknown"
    return "ctx_" + _hash(*[fields.get(k) for k in sorted(fields)])


# ---------------------------------------------------------------------------
# main normalization
# ---------------------------------------------------------------------------

def normalize(run_id=None):
    data_root = config.data_dir()
    if run_id is None:
        latest = data_root / "raw" / "LATEST"
        if not latest.exists():
            raise SystemExit("[normalize] no LATEST run - run retrieve first")
        run_id = latest.read_text(encoding="utf-8").strip()

    raw_dir = data_root / "raw" / run_id
    relations = json.loads((raw_dir / "subnetwork.json").read_text(encoding="utf-8"))
    evidence_by_hash = json.loads((raw_dir / "evidence.json").read_text(encoding="utf-8"))
    raw_manifest = json.loads((raw_dir / "manifest.json").read_text(encoding="utf-8"))
    retrieved_at = raw_manifest.get("finished_at")

    mapping = config.predicates()["indra_mapping"]
    symmetric = set(config.predicates().get("symmetric") or [])

    # --- entities ---------------------------------------------------------
    curies = set()
    for row in relations:
        curies.add(row[REL_SOURCE])
        curies.add(row[REL_TARGET])
    names = resolve_entity_names(
        sorted(curies), data_root / "normalized" / "entity_names.json"
    )

    entities = {}
    for curie in sorted(curies):
        namespace, accession = parse_curie(curie)
        info = names.get(curie, {})
        eid = entity_id(namespace, accession)
        entities[eid] = {
            "id": eid,
            "namespace": namespace,
            "accession": accession,
            "entity_type": info.get("entity_type", "unknown"),
            "preferred_name": info.get("preferred_name"),
            "long_name": info.get("long_name"),
            "taxon_id": info.get("taxon_id"),
        }

    # --- claims / evidence / documents / provenance -----------------------
    claims = {}
    documents = {}
    evidence_rows = {}
    provenance_rows = {}
    contexts = {"ctx_unknown": {
        "id": "ctx_unknown",
        "taxon_id": None,
        "tissue": None,
        "cell_type": None,
        "cell_line": None,
        "disease": None,
        "location": None,
        "note": "source provided no structured context",
    }}

    stats = {
        "relations_in": len(relations),
        "claims_unsigned": 0,
        "claims_signed": 0,
        "relations_unmapped": 0,
        "evidence_total": 0,
        "evidence_negated": 0,
        "evidence_with_quote": 0,
        "evidence_without_document": 0,
        "evidence_with_context": 0,
        "documents_without_date": 0,
    }

    for row in relations:
        stmt_type = row[REL_TYPE]
        spec = mapping.get(stmt_type)
        if spec is None:
            stats["relations_unmapped"] += 1
            continue

        subject_curie, object_curie = row[REL_SOURCE], row[REL_TARGET]
        predicate = spec["predicate"]
        effect_sign = spec["effect_sign"]

        # Canonicalize symmetric predicates so A-binds-B and B-binds-A dedupe.
        if predicate in symmetric:
            subject_curie, object_curie = sorted([subject_curie, object_curie])

        subject_ns, subject_acc = parse_curie(subject_curie)
        object_ns, object_acc = parse_curie(object_curie)
        subject = entity_id(subject_ns, subject_acc)
        obj = entity_id(object_ns, object_acc)

        stmt_hash = str(row[REL_HASH])
        records = evidence_by_hash.get(stmt_hash) or []

        # Negation is per-evidence in the source. A claim is marked negated only
        # when every supporting record is negated - and even then the sign is
        # never flipped.
        negation_flags = [
            bool((r.get("epistemics") or {}).get("negated")) for r in records
        ]
        all_negated = bool(negation_flags) and all(negation_flags)

        claim_id = "clm_" + _hash(
            subject, predicate, obj, "ctx_unknown", all_negated, stmt_type
        )
        if claim_id not in claims:
            claims[claim_id] = {
                "id": claim_id,
                "subject_id": subject,
                "predicate": predicate,
                "object_id": obj,
                "effect_sign": effect_sign,
                "causal": spec["causal"],
                "context_id": "ctx_unknown",
                "negated": all_negated,
                "epistemic_status": "negated" if all_negated else "asserted",
                "qualifiers_json": {"indra_statement_type": stmt_type},
                "source_statement_hash": stmt_hash,
                "source_counts": row[REL_SOURCE_COUNTS],
                "evidence_ids": [],
                "document_ids": [],
                "support_count": 0,
            }
            if effect_sign is None:
                stats["claims_unsigned"] += 1
            else:
                stats["claims_signed"] += 1
        claim = claims[claim_id]

        for record in records:
            stats["evidence_total"] += 1
            text_refs = record.get("text_refs") or {}
            pmid = record.get("pmid") or text_refs.get("PMID")
            pmcid = text_refs.get("PMCID")
            doi = text_refs.get("DOI")
            quote = record.get("text")
            negated = bool((record.get("epistemics") or {}).get("negated"))
            source_api = record.get("source_api")
            source_hash = record.get("source_hash")

            if negated:
                stats["evidence_negated"] += 1
            if quote:
                stats["evidence_with_quote"] += 1

            # one document per publication, regardless of how many resources
            # or sentences report it
            if pmid:
                doc_id = "PMID:" + str(pmid)
            elif pmcid:
                doc_id = "PMCID:" + str(pmcid)
            elif doi:
                doc_id = "DOI:" + str(doi)
            else:
                doc_id = None
                stats["evidence_without_document"] += 1

            if doc_id and doc_id not in documents:
                documents[doc_id] = {
                    "id": doc_id,
                    "pmid": str(pmid) if pmid else None,
                    "pmcid": pmcid,
                    "doi": doi,
                    # CoGEx evidence carries no publication date. Not inferred,
                    # not substituted with the retrieval date. Phase B fills this
                    # from NCBI ESummary.
                    "publication_date": None,
                    "date_precision": "unknown",
                    "publication_type": None,
                    "license": None,
                    "text_hash": None,
                    "retraction_status": "unchecked",
                }
                stats["documents_without_date"] += 1

            context_fields = extract_context(record)
            ctx_id = context_key(context_fields)
            if ctx_id != "ctx_unknown":
                stats["evidence_with_context"] += 1
                if ctx_id not in contexts:
                    entry = {"id": ctx_id}
                    entry.update(context_fields)
                    contexts[ctx_id] = entry

            evidence_id = "evd_" + _hash(claim_id, source_hash, doc_id, quote)
            if evidence_id not in evidence_rows:
                evidence_rows[evidence_id] = {
                    "id": evidence_id,
                    "claim_id": claim_id,
                    "document_id": doc_id,
                    "text_ref": {"pmid": pmid, "pmcid": pmcid, "doi": doi},
                    "quote": quote,
                    "start_offset": None,
                    "end_offset": None,
                    "section": None,
                    # Experimental basis is NOT available from this source.
                    "experimental_basis": "unknown",
                    "source_evidence_code": source_api,
                    "context_id": ctx_id,
                    "negated": negated,
                    "review_status": "unreviewed",
                    "extraction_run_id": run_id,
                }
                claim["evidence_ids"].append(evidence_id)

            provenance_id = "prv_" + _hash(claim_id, evidence_id, "indra_cogex", source_hash)
            provenance_rows[provenance_id] = {
                "id": provenance_id,
                "claim_id": claim_id,
                "evidence_id": evidence_id,
                "source": "indra_cogex",
                "upstream_resource": source_api,
                "source_record_id": source_hash,
                "source_release": None,
                "retrieved_at": retrieved_at,
                "license": "see config/sources.yaml - upstream terms vary",
                "raw_ref": "data/raw/" + run_id + "/evidence.json#" + stmt_hash,
            }

    # Recompute evidence stats from the DEDUPLICATED rows. Counting during the
    # relation loop double-counts, because many source rows collapse into one
    # claim and re-process the same evidence list.
    stats["evidence_total"] = len(evidence_rows)
    stats["evidence_with_quote"] = sum(1 for r in evidence_rows.values() if r["quote"])
    stats["evidence_negated"] = sum(1 for r in evidence_rows.values() if r["negated"])
    stats["evidence_without_document"] = sum(
        1 for r in evidence_rows.values() if not r["document_id"]
    )
    stats["evidence_with_context"] = sum(
        1 for r in evidence_rows.values() if r["context_id"] != "ctx_unknown"
    )
    stats["documents_without_date"] = sum(
        1 for d in documents.values() if d["publication_date"] is None
    )

    # support counts: distinct non-negated documents per claim
    for claim in claims.values():
        docs = set()
        for evidence_id in claim["evidence_ids"]:
            row = evidence_rows[evidence_id]
            if row["negated"] or not row["document_id"]:
                continue
            docs.add(row["document_id"])
        claim["document_ids"] = sorted(docs)
        claim["support_count"] = len(docs)

    tables = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "normalized_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "entities": list(entities.values()),
        "contexts": list(contexts.values()),
        "claims": list(claims.values()),
        "documents": list(documents.values()),
        "evidence": list(evidence_rows.values()),
        "provenance": list(provenance_rows.values()),
        "stats": stats,
    }

    out_dir = data_root / "normalized" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tables.json").write_text(json.dumps(tables, indent=1), encoding="utf-8")
    (data_root / "normalized" / "LATEST").write_text(run_id, encoding="utf-8")

    print("[normalize] entities   " + str(len(entities)))
    print("[normalize] claims     " + str(len(claims))
          + " (signed " + str(stats["claims_signed"])
          + ", unsigned " + str(stats["claims_unsigned"]) + ")")
    print("[normalize] documents  " + str(len(documents)))
    print("[normalize] evidence   " + str(len(evidence_rows))
          + " (negated " + str(stats["evidence_negated"])
          + ", with quote " + str(stats["evidence_with_quote"]) + ")")
    print("[normalize] provenance " + str(len(provenance_rows)))
    print("[normalize] evidence carrying structured context: "
          + str(stats["evidence_with_context"]))
    print("[normalize] documents with no publication date: "
          + str(stats["documents_without_date"]))
    print("[normalize] wrote " + str(out_dir / "tables.json"))
    return out_dir


def main(argv=None):
    parser = argparse.ArgumentParser(description="Normalize a raw CoGEx run")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)
    normalize(args.run_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
