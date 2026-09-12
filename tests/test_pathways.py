"""Layered pathway search: ranking, layering and direction basis.

HANDOVER.md s7: rank by the thinnest step, penalise promiscuous intermediates,
collapse to one row per target. s4: support and dispute are never netted.
"""
from __future__ import annotations

import pytest

from nucleolus.graph import pathways as pw
from nucleolus.graph.queries import Snapshot


def _claim(cid, subj, pred, obj, sign, papers, causal=True):
    return {
        "id": cid, "subject_id": subj, "predicate": pred, "object_id": obj,
        "effect_sign": sign, "causal": causal, "context_id": "ctx_unknown",
        "negated": False, "epistemic_status": "asserted", "qualifiers_json": {},
        "source_statement_hash": cid, "source_counts": {"reach": papers},
        "evidence_ids": [], "document_ids": [], "support_count": papers,
        "n_papers": papers, "n_primary": papers, "n_retracted": 0,
        "n_sentences": papers, "sole_support_retracted": False,
        "earliest_publication_date": None,
    }


def _snapshot(claims, extra_nodes=()):
    ids = set()
    for c in claims:
        ids.add(c["subject_id"])
        ids.add(c["object_id"])
    ids.update(extra_nodes)
    entities = [
        {"id": i, "namespace": "HGNC", "accession": i.split(":")[1],
         "entity_type": "gene_protein", "preferred_name": "N" + i.split(":")[1],
         "long_name": None, "taxon_id": 9606}
        for i in sorted(ids)
    ]
    payload = {
        "id": "t", "schema_version": 1, "created_at": "2026-01-01T00:00:00+00:00",
        "checksum": "sha256:t", "coverage": {}, "limitations": [], "license_note": "",
        "query": {}, "entities": entities,
        "contexts": [{"id": "ctx_unknown", "taxon_id": None, "tissue": None,
                      "cell_type": None, "cell_line": None, "disease": None,
                      "location": None}],
        "claims": claims, "documents": [], "evidence": [], "provenance": [],
    }
    return Snapshot(payload, path=None)


# ---------------------------------------------------------------------------
# direction and its basis
# ---------------------------------------------------------------------------

def test_agreeing_claims_give_an_undisputed_direction():
    claims = [_claim("a", "HGNC:1", "activates", "HGNC:2", 1, 10)]
    sign, basis = pw._leg_sign(claims)
    assert (sign, basis) == (1, "undisputed")


def test_evenly_split_evidence_asserts_no_direction():
    """The core rule: an edge asserted 10 times and denied 10 times is
    contested, not neutral and not positive."""
    claims = [
        _claim("a", "HGNC:1", "activates", "HGNC:2", 1, 10),
        _claim("b", "HGNC:1", "inhibits", "HGNC:2", -1, 10),
    ]
    sign, basis = pw._leg_sign(claims)
    assert sign is None
    assert basis == "contested"


def test_lopsided_evidence_gives_a_direction_but_says_so():
    claims = [
        _claim("a", "HGNC:1", "activates", "HGNC:2", 1, 24),
        _claim("b", "HGNC:1", "inhibits", "HGNC:2", -1, 1),
    ]
    sign, basis = pw._leg_sign(claims)
    assert sign == 1
    assert basis == "dominant"


def test_unsigned_claims_give_no_direction():
    claims = [_claim("a", "HGNC:1", "binds", "HGNC:2", None, 30, causal=False)]
    sign, basis = pw._leg_sign(claims)
    assert sign is None
    assert basis == "unsigned"


def test_minority_is_always_reported_even_when_dominant():
    claims = [
        _claim("a", "HGNC:1", "activates", "HGNC:2", 1, 24),
        _claim("b", "HGNC:1", "inhibits", "HGNC:2", -1, 1),
    ]
    assert pw._leg_contest(claims) == {"pos": 24, "neg": 1}


def test_leg_weight_is_not_a_sum_across_opposing_claims():
    """Two opposing claims are a disagreement, not double the evidence."""
    claims = [
        _claim("a", "HGNC:1", "activates", "HGNC:2", 1, 10),
        _claim("b", "HGNC:1", "inhibits", "HGNC:2", -1, 8),
    ]
    assert pw._leg_weight(claims) == 10


# ---------------------------------------------------------------------------
# ranking
# ---------------------------------------------------------------------------

def test_rank_is_set_by_the_thinnest_step_not_the_total():
    """A route 5 -> 900 must not outrank a route 40 -> 40."""
    claims = [
        _claim("a1", "HGNC:1", "activates", "HGNC:2", 1, 5),
        _claim("a2", "HGNC:2", "activates", "HGNC:9", 1, 900),
        _claim("b1", "HGNC:1", "activates", "HGNC:3", 1, 40),
        _claim("b2", "HGNC:3", "activates", "HGNC:8", 1, 40),
    ]
    result = pw.pathways(_snapshot(claims), "HGNC:1")
    scores = {r["target_id"]: r["weakest_leg_papers"] for r in result["routes"]}
    assert scores["HGNC:9"] == 5
    assert scores["HGNC:8"] == 40
    order = [r["target_id"] for r in result["routes"]]
    assert order.index("HGNC:8") < order.index("HGNC:9")


def test_promiscuous_intermediate_is_penalised():
    """Two routes with identical support: the one through a hub scores lower."""
    claims = [
        _claim("h1", "HGNC:1", "activates", "HGNC:2", 1, 10),  # HGNC:2 is a hub
        _claim("h2", "HGNC:2", "activates", "HGNC:50", 1, 10),
        _claim("s1", "HGNC:1", "activates", "HGNC:3", 1, 10),  # HGNC:3 is specific
        _claim("s2", "HGNC:3", "activates", "HGNC:51", 1, 10),
    ]
    # give HGNC:2 many other connections so its degree is high
    for n in range(10, 40):
        claims.append(_claim(f"x{n}", "HGNC:2", "activates", f"HGNC:{n}", 1, 1))
    result = pw.pathways(_snapshot(claims), "HGNC:1", max_targets=60)
    by_target = {r["target_id"]: r for r in result["routes"]}
    assert by_target["HGNC:50"]["specificity"] < by_target["HGNC:51"]["specificity"]
    assert by_target["HGNC:50"]["score"] < by_target["HGNC:51"]["score"]


def test_one_row_per_target():
    """Several routes to the same target collapse to the best-scoring one."""
    claims = [
        _claim("a1", "HGNC:1", "activates", "HGNC:2", 1, 10),
        _claim("a2", "HGNC:2", "activates", "HGNC:9", 1, 10),
        _claim("b1", "HGNC:1", "activates", "HGNC:3", 1, 2),
        _claim("b2", "HGNC:3", "activates", "HGNC:9", 1, 2),
    ]
    result = pw.pathways(_snapshot(claims), "HGNC:1")
    targets = [r["target_id"] for r in result["routes"]]
    assert targets.count("HGNC:9") == 1
    best = next(r for r in result["routes"] if r["target_id"] == "HGNC:9")
    assert best["nodes"] == ["HGNC:1", "HGNC:2", "HGNC:9"]


# ---------------------------------------------------------------------------
# layering
# ---------------------------------------------------------------------------

def test_a_node_that_carries_traffic_onward_is_an_intermediate():
    """Using max() here once emptied the middle column entirely: most
    intermediates are also targets in their own right."""
    claims = [
        _claim("a", "HGNC:1", "activates", "HGNC:2", 1, 10),   # direct target
        _claim("b", "HGNC:2", "activates", "HGNC:3", 1, 10),   # ... and onward
    ]
    result = pw.pathways(_snapshot(claims), "HGNC:1")
    layer = {n["id"]: n["layer"] for n in result["nodes"]}
    assert layer["HGNC:1"] == 0
    assert layer["HGNC:2"] == 1, "a node with onward traffic belongs in the middle"
    assert layer["HGNC:3"] == 2


def test_unsigned_relations_never_carry_a_route_direction():
    claims = [
        _claim("a", "HGNC:1", "binds", "HGNC:2", None, 30, causal=False),
    ]
    result = pw.pathways(_snapshot(claims), "HGNC:1")
    assert result["routes"] == []


def test_contested_leg_makes_the_whole_route_directionless():
    claims = [
        _claim("a", "HGNC:1", "activates", "HGNC:2", 1, 10),
        _claim("b", "HGNC:2", "activates", "HGNC:3", 1, 5),
        _claim("c", "HGNC:2", "inhibits", "HGNC:3", -1, 5),
    ]
    result = pw.pathways(_snapshot(claims), "HGNC:1")
    route = next(r for r in result["routes"] if r["target_id"] == "HGNC:3")
    assert route["implied_direction"] is None
    assert route["direction_basis"] == "contested"


def test_signed_routes_are_capped_at_two_hops():
    claims = [
        _claim("a", "HGNC:1", "activates", "HGNC:2", 1, 10),
        _claim("b", "HGNC:2", "activates", "HGNC:3", 1, 10),
        _claim("c", "HGNC:3", "activates", "HGNC:4", 1, 10),
    ]
    result = pw.pathways(_snapshot(claims), "HGNC:1", max_hops=5)
    assert result["filters"]["max_hops"] == 2
    assert all(r["hops"] <= 2 for r in result["routes"])
    assert "HGNC:4" not in {r["target_id"] for r in result["routes"]}


def test_min_papers_floor_excludes_thin_legs():
    claims = [
        _claim("a", "HGNC:1", "activates", "HGNC:2", 1, 10),
        _claim("b", "HGNC:1", "activates", "HGNC:3", 1, 1),
    ]
    result = pw.pathways(_snapshot(claims), "HGNC:1", min_papers=5)
    assert {r["target_id"] for r in result["routes"]} == {"HGNC:2"}


def test_unknown_source_raises():
    with pytest.raises(KeyError):
        pw.pathways(_snapshot([_claim("a", "HGNC:1", "activates", "HGNC:2", 1, 1)]),
                    "HGNC:999")
