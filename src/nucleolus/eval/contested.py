"""Build a review set of contested pairs, to find out WHY they disagree.

Half of all signed gene pairs in the snapshot carry claims in both directions.
That figure is usually read as "the literature is uncertain". A hand sample of
four pairs suggested otherwise - every one was an extraction fault, not a
scientific dispute:

  TREM2 -> MAPT      both sentences said TREM2 protects against tau
  TP53  -> PTGS2     the sentence's real subject was p50/p65, not p53
  ATXN2 -> TARDBP    one claim was about toxicity, the other about mRNA half-life
  PTGS2 -> TP53      the supporting sentence described the reverse direction

This module builds the sheet needed to test that at scale. It does not decide
anything: it pairs each disagreement with the actual sentences on both sides so
a human (or, clearly labelled as such, a model) can classify it.

Categories, deliberately distinguishing scientific from mechanical causes:

  genuine_disagreement  comparable evidence, opposite results
  context_difference    different species / cell type / dose / timepoint
  readout_conflation    one node standing for abundance vs activity vs pathology
  polarity_error        the sentence contradicts the sign it was filed under
  co_mention_error      the subject of the sentence is a third entity
  direction_error       the sentence describes the reverse edge
  uninterpretable       the sentence does not support any reading
"""
from __future__ import annotations

import argparse
import collections
import json
import sys

from nucleolus import config

CATEGORIES = [
    "genuine_disagreement",
    "context_difference",
    "readout_conflation",
    "polarity_error",
    "co_mention_error",
    "direction_error",
    "uninterpretable",
]

CAUSAL = {"activates", "inhibits", "increases_amount", "decreases_amount"}


def load_snapshot(snapshot_id: str | None = None) -> dict:
    snapshots = config.data_dir() / "snapshots"
    if snapshot_id is None:
        snapshot_id = (snapshots / "CURRENT").read_text(encoding="utf-8").strip()
    return json.loads((snapshots / f"{snapshot_id}.json").read_text(encoding="utf-8"))


def build(snapshot: dict, limit: int, quotes_per_side: int = 2) -> dict:
    entities = {e["id"]: e for e in snapshot["entities"]}
    documents = {d["id"]: d for d in snapshot["documents"]}

    evidence_by_claim: dict[str, list[dict]] = collections.defaultdict(list)
    for row in snapshot["evidence"]:
        if row.get("quote"):
            evidence_by_claim[row["claim_id"]].append(row)

    # One entry per ordered pair that carries BOTH signs with real paper support.
    pairs: dict[tuple[str, str], dict[int, dict]] = collections.defaultdict(dict)
    for claim in snapshot["claims"]:
        if not claim.get("causal") or claim.get("predicate") not in CAUSAL:
            continue
        if claim.get("effect_sign") not in (-1, 1) or not claim.get("n_papers"):
            continue
        pairs[(claim["subject_id"], claim["object_id"])][claim["effect_sign"]] = claim

    contested = [(key, sides) for key, sides in pairs.items() if len(sides) == 2]

    # Most-supported first: those are the ones a reader would actually meet.
    contested.sort(key=lambda kv: -min(c["n_papers"] for c in kv[1].values()))

    def side(claim: dict) -> dict:
        rows = sorted(
            evidence_by_claim.get(claim["id"], []),
            key=lambda r: (documents.get(r["document_id"], {}).get("publication_date") or "", r["id"]),
            reverse=True,
        )
        quotes = []
        for row in rows[:quotes_per_side]:
            document = documents.get(row["document_id"]) or {}
            quotes.append({
                "evidence_id": row["id"],
                "quote": row["quote"],
                "publication_id": row.get("document_id"),
                "publication_date": document.get("publication_date"),
                "is_primary": document.get("is_primary"),
                "retracted": document.get("retraction_status") == "retracted",
                "reader": row.get("source_evidence_code"),
                "context_id": row.get("context_id"),
            })
        return {
            "claim_id": claim["id"],
            "predicate": claim["predicate"],
            "n_papers": claim["n_papers"],
            "n_sentences": claim.get("n_sentences"),
            "n_primary": claim.get("n_primary"),
            "indra_statement_type": (claim.get("qualifiers_json") or {}).get("indra_statement_type"),
            "quotes": quotes,
        }

    items = []
    for (subject, obj), sides in contested[:limit]:
        positive, negative = sides[1], sides[-1]
        items.append({
            "pair_id": f"{subject}__{obj}",
            "subject": {"id": subject, "name": entities[subject].get("preferred_name")},
            "object": {"id": obj, "name": entities[obj].get("preferred_name")},
            "minority_share": round(
                min(positive["n_papers"], negative["n_papers"])
                / (positive["n_papers"] + negative["n_papers"]), 3),
            "raises": side(positive),
            "lowers": side(negative),
            # to be filled by a reviewer, or by a clearly-labelled model pass
            "label": None,
            "labeller": None,
            "note": None,
        })

    return {
        "snapshot_id": snapshot["id"],
        "snapshot_checksum": snapshot.get("checksum"),
        "categories": CATEGORIES,
        "contested_pairs_total": len(contested),
        "signed_pairs_total": len(pairs),
        "contested_rate": round(len(contested) / len(pairs), 3) if pairs else None,
        "items": items,
        "instructions": (
            "For each pair read BOTH sides' quotes and choose one category. "
            "Only genuine_disagreement and context_difference are scientific; the "
            "rest are extraction faults. A label is a claim about the sentences "
            "shown, not about the underlying biology."
        ),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--snapshot", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    snapshot = load_snapshot(args.snapshot)
    sheet = build(snapshot, args.limit)

    out_dir = config.REPO_ROOT / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = args.out and config.REPO_ROOT / args.out or out_dir / "contested_review.json"
    path.write_text(json.dumps(sheet, indent=1), encoding="utf-8")

    print(f"[contested] snapshot {sheet['snapshot_id']}")
    print(f"[contested] signed ordered pairs      {sheet['signed_pairs_total']}")
    print(f"[contested] contested both directions {sheet['contested_pairs_total']}"
          f" ({100 * sheet['contested_rate']:.0f}%)")
    print(f"[contested] review items written      {len(sheet['items'])}")
    print(f"[contested] -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
