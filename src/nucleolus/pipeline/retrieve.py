"""Retrieval stage: seeds -> verified IDs -> CoGEx subnetwork -> immutable raw cache.

Writes data/raw/<run_id>/ containing manifest.json, hgnc_resolution.json,
subnetwork.json and evidence.json. Nothing here normalizes or interprets:
raw responses are preserved verbatim so a rerun is auditable.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import sys
import time

import httpx

from nucleolus import config
from nucleolus.pipeline.sources.cogex import (
    REL_HASH,
    REL_SOURCE,
    REL_TARGET,
    REL_TYPE,
    CogexClient,
    CogexError,
)

HGNC_FETCH = "https://rest.genenames.org/fetch/symbol/{symbol}"

# MeSH descriptors used to widen the node set beyond the human seed list.
# Measured 2026-09-13 against CoGEx. Counts are genes returned per descriptor.
# MeSH "Aging" (D000375), Parkinson Disease (D010300) and Lewy Body Disease
# (D020961) all return ZERO genes - the ageing axis comes from seeds.yaml
# instead, not from disease association.
DEFAULT_DISEASES = [
    # core cognitive ageing / neurodegeneration
    ("mesh", "D000544", "Alzheimer Disease"),
    ("mesh", "D009410", "Nerve Degeneration"),
    ("mesh", "D008569", "Memory Disorders"),
    ("mesh", "D019636", "Neurodegenerative Diseases"),
    ("mesh", "D003072", "Cognition"),
    ("mesh", "D003704", "Dementia"),
    ("mesh", "D060825", "Cognitive Dysfunction"),
    ("mesh", "D001927", "Brain Diseases"),
    ("mesh", "D001284", "Atrophy"),
    ("mesh", "D000690", "Amyotrophic Lateral Sclerosis"),
    ("mesh", "D057180", "Frontotemporal Dementia"),
    ("mesh", "D006816", "Huntington Disease"),
    # vascular contribution to cognitive decline
    ("mesh", "D016649", "Dementia, Vascular"),
    ("mesh", "D020521", "Stroke"),
    ("mesh", "D002545", "Brain Ischemia"),
    ("mesh", "D000860", "Hypoxia"),
    ("mesh", "D000855", "Anoxia"),
    # neuroinflammation / glia / white matter
    ("mesh", "D007249", "Inflammation"),
    ("mesh", "D009103", "Multiple Sclerosis"),
    ("mesh", "D005902", "Gliosis"),
    ("mesh", "D009837", "Oligodendroglia"),
    ("mesh", "D007964", "Leukoencephalopathy"),
    ("mesh", "D018476", "Oxidative Stress"),
    # late-life depression is a recognised dementia risk factor
    ("mesh", "D003863", "Depression"),
]

# CoGEx rejects indra_subnetwork_meta with >=400 nodes ("Number of nodes must be
# less than 400"), and the endpoint returns only the subgraph INDUCED among the
# nodes it is given. Splitting the set and unioning the results would therefore
# silently drop every edge that crosses a chunk boundary. Querying all chunk
# PAIRS instead keeps the result identical to one whole-set call: any edge has
# both endpoints in some pair. k chunks cost k(k+1)/2 calls.
SUBNETWORK_NODE_LIMIT = 399


def _subnetwork_all_pairs(client, nodes, limit=SUBNETWORK_NODE_LIMIT):
    """Induced relations among `nodes`, chunked to respect the server cap."""
    if len(nodes) <= limit:
        return client.subnetwork_meta(nodes)

    import math

    chunk_count = math.ceil(2 * len(nodes) / limit)
    size = math.ceil(len(nodes) / chunk_count)
    chunks = [nodes[i : i + size] for i in range(0, len(nodes), size)]
    calls = len(chunks) * (len(chunks) + 1) // 2
    print(
        "[retrieve] node set exceeds the "
        + str(limit)
        + "-node server cap: querying "
        + str(len(chunks))
        + " chunks as "
        + str(calls)
        + " pairwise calls"
    )
    seen, merged = set(), []
    for i in range(len(chunks)):
        for j in range(i, len(chunks)):
            batch = chunks[i] if i == j else chunks[i] + chunks[j]
            for row in client.subnetwork_meta(batch):
                key = (row[REL_SOURCE], row[REL_TARGET], row[REL_TYPE], row[REL_HASH])
                if key not in seen:
                    seen.add(key)
                    merged.append(row)
    return merged


STATUS_FLAG = {
    "verified": "ok",
    "mismatch": "MISMATCH",
    "not_found": "NOT FOUND",
    "unresolved": "UNRESOLVED",
}


def verify_seed_ids(seed_list):
    """Check each asserted HGNC ID against the HGNC REST API.

    A mismatch is recorded as a hard failure - never silently corrected.
    """
    resolved = []
    failures = []
    with httpx.Client(timeout=30.0, headers={"Accept": "application/json"}) as client:
        for seed in seed_list:
            symbol = seed["symbol"]
            asserted = str(seed.get("hgnc_id", "")).replace("HGNC:", "")
            record = {
                "symbol": symbol,
                "asserted_hgnc_id": asserted,
                "rationale": seed.get("rationale"),
            }
            try:
                response = client.get(HGNC_FETCH.format(symbol=symbol))
                docs = response.json().get("response", {}).get("docs", [])
            except Exception as exc:  # network or response-shape problem
                record.update(status="unresolved", error=str(exc)[:200])
                failures.append(symbol + ": lookup failed (" + str(exc)[:80] + ")")
                resolved.append(record)
                continue

            if not docs:
                record.update(status="not_found")
                failures.append(symbol + ": no HGNC record")
                resolved.append(record)
                continue

            actual = docs[0]["hgnc_id"].replace("HGNC:", "")
            record.update(
                status="verified" if actual == asserted else "mismatch",
                actual_hgnc_id=actual,
                preferred_name=docs[0].get("name"),
                taxon_id=9606,
            )
            if actual != asserted:
                failures.append(
                    symbol + ": asserted HGNC:" + asserted + " but HGNC says HGNC:" + actual
                )
            resolved.append(record)
    return resolved, failures


def run(max_nodes, fetch_evidence, diseases, evidence_for="signed", max_evidence_per_statement=None):
    started_at = dt.datetime.now(dt.timezone.utc)
    run_id = started_at.strftime("%Y%m%dT%H%M%SZ")
    out_dir = config.data_dir() / "raw" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    seeds_cfg = config.seeds()
    sources_cfg = config.sources()["sources"]["cogex"]

    print("[retrieve] run_id=" + run_id)
    print("[retrieve] output=" + str(out_dir))

    # --- 1. verify seed identifiers --------------------------------------
    print("[retrieve] verifying " + str(len(seeds_cfg["seeds"])) + " seed HGNC IDs ...")
    resolution, failures = verify_seed_ids(seeds_cfg["seeds"])
    (out_dir / "hgnc_resolution.json").write_text(
        json.dumps(resolution, indent=2), encoding="utf-8"
    )
    for record in resolution:
        flag = STATUS_FLAG.get(record["status"], "UNRESOLVED")
        actual = record.get("actual_hgnc_id", "?")
        print("           {0:<9} HGNC:{1:<7} {2}".format(record["symbol"], actual, flag))
    if failures:
        print("[retrieve] SEED VERIFICATION FAILURES:")
        for failure in failures:
            print("           - " + failure)

    seed_nodes = [("HGNC", r["actual_hgnc_id"]) for r in resolution if r["status"] == "verified"]
    if not seed_nodes:
        raise SystemExit("[retrieve] no seed resolved - aborting rather than querying blind")

    # --- 2. expand node set from disease associations ---------------------
    client = CogexClient(
        base_url=config.env().get("COGEX_BASE_URL", sources_cfg["base_url"]),
        rate_limit_rps=sources_cfg.get("rate_limit_rps", 3),
    )
    nodes = list(seed_nodes)
    seen = set(n[1] for n in nodes)
    disease_genes = {}
    relations = []
    evidence = {}
    truncated = False
    type_counts = {}
    mapping = config.predicates()["indra_mapping"]
    signed = []

    with client:
        for namespace, identifier, label in diseases:
            try:
                genes = client.genes_for_disease(namespace, identifier)
            except CogexError as exc:
                print("[retrieve] disease query " + label + " FAILED: " + str(exc)[:160])
                disease_genes[label] = []
                continue
            symbols = []
            for gene in genes:
                data = gene.get("data", {})
                if data.get("db_ns") != "HGNC" or not data.get("db_id"):
                    continue
                symbols.append(data.get("name"))
                if data["db_id"] not in seen and len(nodes) < max_nodes:
                    nodes.append(("HGNC", data["db_id"]))
                    seen.add(data["db_id"])
            disease_genes[label] = symbols
            print("[retrieve] " + label + ": " + str(len(symbols)) + " associated genes")

        truncated = len(nodes) >= max_nodes
        print(
            "[retrieve] node set = "
            + str(len(nodes))
            + " (cap "
            + str(max_nodes)
            + ", truncated="
            + str(truncated)
            + ")"
        )

        # --- 3. induced subnetwork ---------------------------------------
        t0 = time.monotonic()
        relations = _subnetwork_all_pairs(client, nodes)
        elapsed = time.monotonic() - t0
        print("[retrieve] " + str(len(relations)) + " relations in " + format(elapsed, ".2f") + "s")
        (out_dir / "subnetwork.json").write_text(json.dumps(relations, indent=1), encoding="utf-8")

        for row in relations:
            type_counts[row[REL_TYPE]] = type_counts.get(row[REL_TYPE], 0) + 1

        signed = [
            r for r in relations if (mapping.get(r[REL_TYPE]) or {}).get("effect_sign") is not None
        ]
        print(
            "[retrieve] signed causal relations: "
            + str(len(signed))
            + " / "
            + str(len(relations))
        )

        # --- 4. evidence ----------------------------------------------------
        # Unsigned relations (binds, phosphorylates) need evidence too: an edge a
        # user can click must be inspectable, whatever its predicate.
        evidence_targets = relations if evidence_for == "all" else signed
        if fetch_evidence and evidence_targets:
            hashes = list(dict.fromkeys(str(r[REL_HASH]) for r in evidence_targets))
            print(
                "[retrieve] fetching evidence for " + str(len(hashes))
                + " unique statements (" + str(len(evidence_targets)) + " relations) ..."
            )
            BATCH = 200
            for start in range(0, len(hashes), BATCH):
                chunk = hashes[start : start + BATCH]
                try:
                    got = client.evidences_for_hashes(chunk)
                except CogexError as exc:
                    got = {}
                    print("           batch FAILED: " + str(exc)[:120])
                for stmt_hash in chunk:
                    records = got.get(stmt_hash, [])
                    # Storing every record for the most-cited statements is what
                    # makes the raw set unmanageable: the distribution is median
                    # 1, p90 11, max ~8000. A cap here leaves the long tail
                    # untouched and is recorded in the manifest, never silent.
                    if max_evidence_per_statement:
                        records = records[:max_evidence_per_statement]
                    evidence[stmt_hash] = records
                print("           " + str(min(start + BATCH, len(hashes))) + "/" + str(len(hashes)))
        (out_dir / "evidence.json").write_text(json.dumps(evidence, indent=1), encoding="utf-8")

        call_log = list(client.call_log)

    # --- 5. manifest -------------------------------------------------------
    total_evidence = sum(len(recs) for recs in evidence.values())
    with_text = sum(1 for recs in evidence.values() for e in recs if e.get("text"))
    with_pmid = sum(
        1
        for recs in evidence.values()
        for e in recs
        if e.get("pmid") or (e.get("text_refs") or {}).get("PMID")
    )

    manifest = {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": "indra_cogex",
        "base_url": client.base_url,
        "seeds_config_version": seeds_cfg.get("version"),
        "seed_verification": {
            "verified": sum(1 for r in resolution if r["status"] == "verified"),
            "failed": len(failures),
            "failures": failures,
        },
        "query": {
            "diseases": [{"ns": d[0], "id": d[1], "label": d[2]} for d in diseases],
            "disease_gene_counts": {k: len(v) for k, v in disease_genes.items()},
            "max_nodes": max_nodes,
            "node_count": len(nodes),
            "truncated": truncated,
            "nodes": [list(n) for n in nodes],
        },
        "results": {
            "relations": len(relations),
            "statement_types": dict(sorted(type_counts.items(), key=lambda kv: -kv[1])),
            "signed_causal": len(signed),
            "unmapped_statement_types": sorted(set(type_counts) - set(mapping)),
            "evidence_statements": len(evidence),
            "evidence_records": total_evidence,
            "evidence_with_quote": with_text,
            "evidence_with_pmid": with_pmid,
            "evidence_scope": evidence_for,
            "max_evidence_per_statement": max_evidence_per_statement,
        },
        "http_calls": len(call_log),
        "call_log_tail": call_log[-20:],
        "license_note": (sources_cfg.get("license_note") or "").strip(),
        "code_version": "nucleolus@0.1.0",
    }
    manifest["input_hash"] = hashlib.sha256(
        json.dumps(manifest["query"], sort_keys=True).encode()
    ).hexdigest()[:16]
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    (config.data_dir() / "raw" / "LATEST").write_text(run_id, encoding="utf-8")

    print(
        "[retrieve] done. evidence: "
        + str(total_evidence)
        + " records, "
        + str(with_text)
        + " with quote, "
        + str(with_pmid)
        + " with PMID"
    )
    return out_dir


def main(argv=None):
    parser = argparse.ArgumentParser(description="Pull an ALS/FTD subnetwork from INDRA CoGEx")
    parser.add_argument("--max-nodes", type=int, default=500)
    parser.add_argument("--no-evidence", action="store_true", help="skip evidence fetch")
    parser.add_argument(
        "--max-evidence-per-statement",
        type=int,
        default=None,
        help="store at most N evidence records per statement (default: all)",
    )
    parser.add_argument(
        "--evidence-for",
        choices=["signed", "all"],
        default="signed",
        help="fetch evidence for signed causal relations only, or for every relation",
    )
    args = parser.parse_args(argv)
    run(
        max_nodes=args.max_nodes,
        fetch_evidence=not args.no_evidence,
        diseases=DEFAULT_DISEASES,
        evidence_for=args.evidence_for,
        max_evidence_per_statement=args.max_evidence_per_statement,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
