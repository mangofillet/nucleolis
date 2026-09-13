"""Resilience/damage showcase projection.

The showcase is the screen most likely to be read as a summary of the biology,
so the rules it must not break are the ones tested here: unsigned relations stay
out, opposing claims are not merged, a contested pair asserts no direction, and
seeded genes missing from the snapshot are reported rather than hidden.
"""
from __future__ import annotations

import networkx as nx
import pytest

from nucleolis.api import axes as axes_mod


class StubSnapshot:
    """Minimal stand-in exposing only what build_axes_view touches."""

    def __init__(self, entities, edges):
        self.id = "test_snapshot"
        self._entities = entities
        self.graph = nx.MultiDiGraph()
        for entity_id, name in entities.items():
            self.graph.add_node(entity_id, preferred_name=name)
        for source, target, claim_id, attrs in edges:
            self.graph.add_edge(source, target, key=claim_id, **attrs)

    def search_nodes(self, query, limit=20):
        out = []
        for entity_id, name in self._entities.items():
            if name.upper() == query.upper():
                out.append(
                    {
                        "id": entity_id,
                        "preferred_name": name,
                        "long_name": None,
                        "degree": self.graph.degree(entity_id),
                    }
                )
        return out[:limit]


def signed(sign, support, causal=True, negated=False):
    return {
        "predicate": "activates" if sign == 1 else "inhibits",
        "effect_sign": sign,
        "causal": causal,
        "negated": negated,
        "support_count": support,
    }


@pytest.fixture
def membership(monkeypatch):
    """SIRT1 on the resilience side, NLRP3 and CDKN2A on the damage side."""
    monkeypatch.setattr(
        axes_mod.config,
        "seeds",
        lambda: {
            "seeds": [
                {"symbol": "SIRT1", "axis": "mitochondrial", "rationale": "r1"},
                {"symbol": "NLRP3", "axis": "neuroinflammation", "rationale": "r2"},
                {"symbol": "CDKN2A", "axis": "senescence", "rationale": "r3"},
                {"symbol": "ABSENTGENE", "axis": "autophagy", "rationale": "r4"},
            ],
            "axes": {
                "resilience": ["mitochondrial", "autophagy"],
                "damage": ["neuroinflammation", "senescence"],
            },
        },
    )


def test_unsigned_relations_are_excluded(membership):
    """A phosphorylation is a mechanism, not a direction of effect."""
    snap = StubSnapshot(
        {"HGNC:1": "SIRT1", "HGNC:2": "NLRP3"},
        [
            (
                "HGNC:1",
                "HGNC:2",
                "c1",
                {
                    "predicate": "phosphorylates",
                    "effect_sign": None,
                    "causal": False,
                    "negated": False,
                    "support_count": 90,
                },
            )
        ],
    )
    view = axes_mod.build_axes_view(snap, max_links=10, min_support=1)
    assert view["links"] == []


def test_opposing_claims_are_not_merged_and_contested_has_no_direction(membership):
    snap = StubSnapshot(
        {"HGNC:1": "SIRT1", "HGNC:2": "NLRP3"},
        [
            ("HGNC:1", "HGNC:2", "c_up", signed(1, 10)),
            ("HGNC:1", "HGNC:2", "c_down", signed(-1, 9)),
        ],
    )
    view = axes_mod.build_axes_view(snap, max_links=10, min_support=1)
    (link,) = view["links"]

    assert link["basis"] == "contested"
    assert link["direction"] is None, "a contested pair must not assert a direction"
    # both counts survive; the minority is never subtracted from the majority
    assert link["support_up"] == 10
    assert link["support_down"] == 9
    assert len(link["claims"]) == 2


def test_dominant_direction_still_reports_the_minority(membership):
    snap = StubSnapshot(
        {"HGNC:1": "SIRT1", "HGNC:2": "NLRP3"},
        [
            ("HGNC:1", "HGNC:2", "c_down", signed(-1, 40)),
            ("HGNC:1", "HGNC:2", "c_up", signed(1, 2)),
        ],
    )
    (link,) = axes_mod.build_axes_view(snap, max_links=10, min_support=1)["links"]
    assert link["basis"] == "dominant"
    assert link["direction"] == -1
    assert link["support_up"] == 2


def test_undisputed_when_only_one_direction_is_supported(membership):
    snap = StubSnapshot(
        {"HGNC:1": "SIRT1", "HGNC:2": "CDKN2A"},
        [("HGNC:1", "HGNC:2", "c1", signed(-1, 7))],
    )
    (link,) = axes_mod.build_axes_view(snap, max_links=10, min_support=1)["links"]
    assert link["basis"] == "undisputed"
    assert link["direction"] == -1


def test_within_side_claims_do_not_cross(membership):
    """NLRP3 and CDKN2A are both on the damage side: not a crossing claim."""
    snap = StubSnapshot(
        {"HGNC:2": "NLRP3", "HGNC:3": "CDKN2A"},
        [("HGNC:2", "HGNC:3", "c1", signed(1, 20))],
    )
    assert axes_mod.build_axes_view(snap, max_links=10, min_support=1)["links"] == []


def test_missing_seeds_are_reported_not_hidden(membership):
    snap = StubSnapshot({"HGNC:1": "SIRT1", "HGNC:2": "NLRP3"}, [])
    view = axes_mod.build_axes_view(snap, max_links=10, min_support=1)
    missing = {m["symbol"] for m in view["seeds_not_in_snapshot"]}
    assert "ABSENTGENE" in missing
    assert "CDKN2A" in missing
    assert "SIRT1" not in missing


def test_truncation_is_reported(membership):
    snap = StubSnapshot(
        {"HGNC:1": "SIRT1", "HGNC:2": "NLRP3", "HGNC:3": "CDKN2A"},
        [
            ("HGNC:1", "HGNC:2", "c1", signed(1, 5)),
            ("HGNC:1", "HGNC:3", "c2", signed(-1, 4)),
        ],
    )
    view = axes_mod.build_axes_view(snap, max_links=1, min_support=1)
    assert view["truncated"] is True
    assert view["total_links"] == 2
    assert len(view["links"]) == 1


def test_min_support_filters_thin_claims(membership):
    snap = StubSnapshot(
        {"HGNC:1": "SIRT1", "HGNC:2": "NLRP3"},
        [("HGNC:1", "HGNC:2", "c1", signed(1, 1))],
    )
    assert axes_mod.build_axes_view(snap, max_links=10, min_support=5)["links"] == []
