"""Build-time evidence cap.

Capping is a storage decision, never an epistemic one. These tests pin the line:
the snapshot may hold fewer sentences, but it must not report fewer papers, and
it must never present a sample as if it were the whole trail.
"""
from __future__ import annotations

from nucleolis.pipeline.build import apply_evidence_cap


def make_tables(evidence_per_claim, quotes=True, docs=True):
    evidence, provenance, claims = [], [], []
    for claim_index, count in enumerate(evidence_per_claim):
        claim_id = f"c{claim_index}"
        ids = []
        for n in range(count):
            eid = f"{claim_id}-e{n:03d}"
            ids.append(eid)
            evidence.append(
                {
                    "id": eid,
                    "claim_id": claim_id,
                    "quote": f"sentence {n}" if quotes else None,
                    "document_id": f"doc{n}" if docs else None,
                }
            )
            provenance.append({"id": f"p-{eid}", "claim_id": claim_id, "evidence_id": eid})
        claims.append(
            {
                "id": claim_id,
                "evidence_ids": ids,
                "support_count": count,      # paper-level counts, set by normalize
                "n_papers": count,
                "n_sentences": count,
            }
        )
    # a provenance row not tied to any single evidence record
    provenance.append({"id": "p-claim-level", "claim_id": "c0", "evidence_id": None})
    return {"claims": claims, "evidence": evidence, "provenance": provenance}


def test_no_cap_is_a_passthrough():
    tables = make_tables([50])
    out, report = apply_evidence_cap(tables, None)
    assert report is None
    assert len(out["evidence"]) == 50
    assert "evidence_capped" not in out["claims"][0]


def test_cap_keeps_at_most_n_per_claim():
    out, report = apply_evidence_cap(make_tables([25, 3, 40]), 10)
    per_claim = {}
    for row in out["evidence"]:
        per_claim[row["claim_id"]] = per_claim.get(row["claim_id"], 0) + 1
    assert per_claim == {"c0": 10, "c1": 3, "c2": 10}
    assert report["claims_capped"] == 2      # c1 was under the cap
    assert report["evidence_dropped"] == (25 - 10) + (40 - 10)


def test_paper_counts_are_never_rewritten():
    """The whole point: 41 papers stays 41 papers even if 10 sentences are kept."""
    out, _ = apply_evidence_cap(make_tables([41]), 10)
    claim = out["claims"][0]
    assert claim["support_count"] == 41
    assert claim["n_papers"] == 41
    assert claim["n_sentences"] == 41


def test_capped_claim_records_the_true_total():
    out, _ = apply_evidence_cap(make_tables([214]), 10)
    claim = out["claims"][0]
    assert claim["evidence_capped"] is True
    assert claim["evidence_total"] == 214
    assert len(claim["evidence_ids"]) == 10


def test_uncapped_claim_is_not_flagged():
    out, _ = apply_evidence_cap(make_tables([4]), 10)
    assert out["claims"][0].get("evidence_capped", False) is False


def test_evidence_ids_stay_consistent_with_kept_rows():
    """A dangling evidence id would fail snapshot validation."""
    out, _ = apply_evidence_cap(make_tables([30, 12]), 5)
    kept = {row["id"] for row in out["evidence"]}
    for claim in out["claims"]:
        assert set(claim["evidence_ids"]) <= kept


def test_provenance_for_dropped_evidence_is_removed_but_claim_level_survives():
    out, _ = apply_evidence_cap(make_tables([30]), 5)
    kept = {row["id"] for row in out["evidence"]}
    for row in out["provenance"]:
        assert row["evidence_id"] is None or row["evidence_id"] in kept
    assert any(r["evidence_id"] is None for r in out["provenance"])


def test_records_with_quotes_are_preferred_over_bare_ones():
    tables = make_tables([6])
    for row in tables["evidence"][:3]:
        row["quote"] = None                  # first three are quoteless
    out, _ = apply_evidence_cap(tables, 3)
    assert all(row["quote"] is not None for row in out["evidence"])


def test_selection_is_deterministic():
    a, _ = apply_evidence_cap(make_tables([60]), 10)
    b, _ = apply_evidence_cap(make_tables([60]), 10)
    assert [r["id"] for r in a["evidence"]] == [r["id"] for r in b["evidence"]]
