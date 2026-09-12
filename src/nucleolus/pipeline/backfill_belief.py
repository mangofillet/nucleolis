"""Backfill INDRA belief and activity state onto an existing snapshot.

Why this exists: the original ingest called `indra_subnetwork_meta`, which
returns [source, target, statement_type, statement_hash, source_counts] and
nothing else. Belief is a statement-level property and was silently absent, so
every confidence path in the application resolved to `belief_method:
"unavailable"` on real data.

`get_stmts_for_stmt_hashes` returns the full Statement, including:
  belief        the assembled confidence score (0.37-0.66 across this graph)
  obj_activity  activity vs abundance on the object - part of the readout
                conflation measured in the contested-pair audit

Every claim already carries `source_statement_hash`, so this recovers both
without re-reading the corpus. Statements that do not come back keep a null
belief: unknown stays unknown.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import time
import urllib.request

from nucleolus import config

ENDPOINT = "get_stmts_for_stmt_hashes"
BATCH = 50


def fetch(base: str, hashes: list[str]) -> dict[str, dict]:
    request = urllib.request.Request(
        f"{base.rstrip('/')}/{ENDPOINT}",
        data=json.dumps({"stmt_hashes": hashes}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.loads(response.read())
    rows = payload if isinstance(payload, list) else (
        payload.get("statements") or payload.get("results") or [])
    out = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("matches_hash") or row.get("id") or "")
        if key:
            out[key] = row
    return out


def backfill(snapshot_id: str | None, base: str) -> dict:
    snapshots = config.data_dir() / "snapshots"
    snapshot_id = snapshot_id or (snapshots / "CURRENT").read_text(encoding="utf-8").strip()
    path = snapshots / f"{snapshot_id}.json"
    snapshot = json.loads(path.read_text(encoding="utf-8"))

    hashes = sorted({str(c["source_statement_hash"]) for c in snapshot["claims"]
                     if c.get("source_statement_hash")})
    print(f"[belief] snapshot {snapshot_id}: {len(snapshot['claims'])} claims, "
          f"{len(hashes)} distinct statement hashes")

    statements: dict[str, dict] = {}
    for start in range(0, len(hashes), BATCH):
        chunk = hashes[start:start + BATCH]
        try:
            statements.update(fetch(base, chunk))
        except Exception as exc:  # noqa: BLE001 - report, never guess a belief
            print(f"  batch {start // BATCH + 1}: FAILED {str(exc)[:70]}")
        print(f"  {min(start + BATCH, len(hashes))}/{len(hashes)} "
              f"({len(statements)} statements recovered)")
        time.sleep(0.3)

    stats = collections.Counter()
    beliefs = []
    for claim in snapshot["claims"]:
        key = str(claim.get("source_statement_hash") or "")
        statement = statements.get(key)
        if not statement:
            claim["belief"] = None
            claim["belief_method"] = "unavailable"
            stats["no_statement_returned"] += 1
            continue
        belief = statement.get("belief")
        claim["belief"] = belief
        claim["belief_method"] = "indra_statement_belief" if belief is not None else "unavailable"
        # Activity vs abundance: the distinction a bare predicate loses.
        for field in ("obj_activity", "subj_activity"):
            if statement.get(field):
                claim[field] = statement[field]
        if belief is None:
            stats["statement_without_belief"] += 1
        else:
            stats["belief_recovered"] += 1
            beliefs.append(belief)

    coverage = len(beliefs) / len(snapshot["claims"]) if snapshot["claims"] else 0
    snapshot.setdefault("coverage", {}).update({
        "claims_with_belief": len(beliefs),
        "belief_coverage": round(coverage, 3),
        "belief_min": round(min(beliefs), 4) if beliefs else None,
        "belief_max": round(max(beliefs), 4) if beliefs else None,
        "belief_median": round(sorted(beliefs)[len(beliefs) // 2], 4) if beliefs else None,
        "claims_with_obj_activity": sum(1 for c in snapshot["claims"] if c.get("obj_activity")),
    })
    snapshot["belief_backfill"] = {
        "endpoint": ENDPOINT,
        "note": "belief is a statement-level assembly score, not a treatment "
                "probability; absent values stay null",
        **dict(stats),
    }
    path.write_text(json.dumps(snapshot, indent=1), encoding="utf-8")

    print(f"\n[belief] recovered            {len(beliefs)}/{len(snapshot['claims'])}"
          f"  ({100 * coverage:.0f}%)")
    if beliefs:
        print(f"[belief] range                {min(beliefs):.3f} - {max(beliefs):.3f}"
              f"   median {sorted(beliefs)[len(beliefs)//2]:.3f}")
    print(f"[belief] obj_activity recovered {snapshot['coverage']['claims_with_obj_activity']}")
    for key, value in stats.items():
        print(f"[belief]   {key:<28} {value}")
    print(f"[belief] -> {path}")
    return snapshot


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", default=None)
    args = parser.parse_args(argv)
    base = config.env().get("COGEX_BASE_URL", "https://discovery.indra.bio/api")
    backfill(args.snapshot, base)
    return 0


if __name__ == "__main__":
    sys.exit(main())
