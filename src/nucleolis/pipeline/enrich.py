"""Enrichment stage: fill document metadata from PubMed.

Runs between normalize and build. Reads data/normalized/<run>/tables.json,
adds publication dates, precision, types and primary-study status to the
documents table, recomputes per-claim independence counts, and writes back.

Cached in data/normalized/pubmed_cache.json so reruns cost nothing.

EXECUTION_PLAN.md s4: publication dates are never inferred and precision is
preserved. HANDOVER.md s9: n_papers and n_primary are kept separate and never
collapsed into one number, so a reader can see which test discounted a claim.
"""
from __future__ import annotations

import argparse
import json
import sys

from nucleolis import config
from nucleolis.pipeline.sources.pubmed import PubMedClient


def enrich(run_id: str | None = None, refresh: bool = False) -> dict:
    data_root = config.data_dir()
    if run_id is None:
        latest = data_root / "normalized" / "LATEST"
        if not latest.exists():
            raise SystemExit("[enrich] no normalized run - run normalize first")
        run_id = latest.read_text(encoding="utf-8").strip()

    tables_path = data_root / "normalized" / run_id / "tables.json"
    tables = json.loads(tables_path.read_text(encoding="utf-8"))
    documents = tables["documents"]

    cache_path = data_root / "normalized" / "pubmed_cache.json"
    cache: dict[str, dict] = {}
    if cache_path.exists() and not refresh:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))

    pmids = [d["pmid"] for d in documents if d.get("pmid")]
    missing = sorted({p for p in pmids if p not in cache})
    print(f"[enrich] {len(documents)} documents, {len(pmids)} with a PMID, "
          f"{len(missing)} not cached")

    if missing:
        env = config.env()
        client = PubMedClient(
            tool=env.get("NCBI_TOOL", "nucleolis"),
            email=env.get("NCBI_EMAIL", ""),
            api_key=env.get("NCBI_API_KEY", ""),
        )
        with client:
            def progress(done: int, total: int) -> None:
                print(f"           {done}/{total}")

            fetched = client.summaries_for_all(missing, progress=progress)
        print(f"[enrich] NCBI returned {len(fetched)} of {len(missing)} "
              f"in {client.calls} calls")
        cache.update(fetched)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, indent=1), encoding="utf-8")

    # --- apply to documents ------------------------------------------------
    stats = {
        "documents": len(documents),
        "dated": 0,
        "precision_day": 0,
        "precision_month": 0,
        "precision_year": 0,
        "precision_unknown": 0,
        "primary": 0,
        "secondary": 0,
        "type_unknown": 0,
        "retracted": 0,
        "not_found_in_pubmed": 0,
    }

    for document in documents:
        pmid = document.get("pmid")
        record = cache.get(str(pmid)) if pmid else None
        if not record:
            document["publication_types"] = []
            document["is_primary"] = None
            if pmid:
                stats["not_found_in_pubmed"] += 1
            stats["precision_unknown"] += 1
            stats["type_unknown"] += 1
            continue

        document["publication_date"] = record["publication_date"]
        document["date_precision"] = record["date_precision"]
        document["publication_type"] = (record["publication_types"] or [None])[0]
        document["publication_types"] = record["publication_types"]
        document["is_primary"] = record["is_primary"]
        document["retraction_status"] = record["retraction_status"]
        if record.get("journal"):
            document["journal"] = record["journal"]

        if record["publication_date"]:
            stats["dated"] += 1
        stats["precision_" + record["date_precision"]] += 1
        if record["is_primary"]:
            stats["primary"] += 1
        elif record["publication_types"]:
            stats["secondary"] += 1
        else:
            stats["type_unknown"] += 1
        if record["retraction_status"] == "retracted":
            stats["retracted"] += 1

    # --- per-claim independence counts, kept separate ----------------------
    by_id = {d["id"]: d for d in documents}
    evidence_by_claim: dict[str, list] = {}
    for row in tables["evidence"]:
        evidence_by_claim.setdefault(row["claim_id"], []).append(row)

    inflation_samples = []
    for claim in tables["claims"]:
        docs = set()
        primary_docs = set()
        retracted_docs = set()
        sentences = 0
        earliest = None
        for row in evidence_by_claim.get(claim["id"], []):
            if row["negated"] or not row["document_id"]:
                continue
            sentences += 1
            docs.add(row["document_id"])
            document = by_id.get(row["document_id"]) or {}
            if document.get("is_primary"):
                primary_docs.add(row["document_id"])
            if document.get("retraction_status") == "retracted":
                retracted_docs.add(row["document_id"])
            date = document.get("publication_date")
            # Only day/month/year strings sort correctly as text prefixes.
            if date and (earliest is None or date < earliest):
                earliest = date

        claim["n_papers"] = len(docs)
        claim["n_primary"] = len(primary_docs)
        claim["n_retracted"] = len(retracted_docs)
        # A claim whose every supporting paper has been withdrawn has no
        # surviving support. Never silently dropped - flagged loudly.
        claim["sole_support_retracted"] = bool(docs) and docs == retracted_docs
        claim["n_sentences"] = sentences
        claim["support_count"] = len(docs)
        claim["earliest_publication_date"] = earliest
        if docs:
            inflation_samples.append(sentences / len(docs))

    if inflation_samples:
        inflation_samples.sort()
        mid = inflation_samples[len(inflation_samples) // 2]
        stats["sentence_inflation_median"] = round(mid, 2)
        stats["sentence_inflation_max"] = round(inflation_samples[-1], 2)

    tables["stats"].update({
        "documents_without_date": stats["documents"] - stats["dated"],
        "documents_dated": stats["dated"],
        "documents_primary": stats["primary"],
        "documents_secondary": stats["secondary"],
        "documents_retracted": stats["retracted"],
    })
    tables["enrichment"] = stats
    tables_path.write_text(json.dumps(tables, indent=1), encoding="utf-8")

    print(f"[enrich] dated {stats['dated']}/{stats['documents']} "
          f"(day {stats['precision_day']}, month {stats['precision_month']}, "
          f"year {stats['precision_year']}, unknown {stats['precision_unknown']})")
    print(f"[enrich] primary {stats['primary']} · secondary {stats['secondary']} "
          f"· type unknown {stats['type_unknown']} · retracted {stats['retracted']}")
    if "sentence_inflation_median" in stats:
        print(f"[enrich] sentences per paper: median "
              f"{stats['sentence_inflation_median']}x, "
              f"max {stats['sentence_inflation_max']}x")
    return stats


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Enrich documents from PubMed")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--refresh", action="store_true", help="ignore the cache")
    args = parser.parse_args(argv)
    enrich(args.run_id, args.refresh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
