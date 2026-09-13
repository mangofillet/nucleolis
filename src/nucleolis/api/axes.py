"""Resilience-vs-damage showcase, read-only over one snapshot.

The brain-ageing question is not "which genes are involved" but "what holds
cognition up, what wears it down, and where do the two meet". `config/seeds.yaml`
assigns every v2 seed to an axis and groups those axes into a resilience side and
a damage side; this endpoint projects the snapshot through that assignment.

It inherits the rules the rest of the service enforces, because a showcase that
quietly relaxes them would be the most misleading screen in the product:

  - Opposing claims are never merged. `A activates B` and `A inhibits B` come
    back as two claims with both support counts, and the pair is labelled
    contested rather than resolved.
  - Direction always carries its basis: undisputed / dominant / contested.
    A contested pair asserts no direction at all.
  - Modifications and bindings are unsigned and are excluded here: a
    phosphorylation is a mechanism, not a direction of effect.
  - Seeds absent from the snapshot are reported, not hidden. An axis that looks
    complete when it is not is worse than an axis with a visible gap.
  - Truncation is reported.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from nucleolis import config

router = APIRouter(tags=["showcase"])

# A minority share at or above this fraction means the literature does not
# agree on a direction. Below it the majority direction is reported as
# dominant, still carrying the minority count.
CONTESTED_MINORITY_SHARE = 0.40


def _axis_membership() -> tuple[dict[str, str], dict[str, list[str]], dict[str, str]]:
    """symbol -> axis, side -> [axis], symbol -> rationale, from seeds.yaml."""
    seeds_cfg = config.seeds()
    sides = seeds_cfg.get("axes") or {}
    by_symbol: dict[str, str] = {}
    rationale: dict[str, str] = {}
    for seed in seeds_cfg.get("seeds", []):
        symbol = (seed.get("symbol") or "").upper()
        if not symbol:
            continue
        by_symbol[symbol] = seed.get("axis") or "unassigned"
        rationale[symbol] = seed.get("rationale") or ""
    return by_symbol, {k: list(v) for k, v in sides.items()}, rationale


def _side_of(axis: str, sides: dict[str, list[str]]) -> str | None:
    for side, axes in sides.items():
        if axis in axes:
            return side
    return None


def build_axes_view(snap, max_links: int, min_support: int) -> dict:
    axis_by_symbol, sides, rationale = _axis_membership()

    # resolve seeded symbols against the snapshot
    placed: dict[str, dict] = {}
    missing: list[dict] = []
    for symbol, axis in axis_by_symbol.items():
        side = _side_of(axis, sides)
        matches = snap.search_nodes(symbol, limit=5)
        exact = next(
            (m for m in matches if (m.get("preferred_name") or "").upper() == symbol),
            None,
        )
        if exact is None:
            missing.append(
                {
                    "symbol": symbol,
                    "axis": axis,
                    "side": side,
                    "reason": "seeded gene has no entity in this snapshot",
                }
            )
            continue
        placed[exact["id"]] = {
            "id": exact["id"],
            "name": exact["preferred_name"],
            "long_name": exact.get("long_name"),
            "axis": axis,
            "side": side,
            "degree": exact.get("degree", 0),
            "rationale": rationale.get(symbol, ""),
        }

    # group by side then axis, preserving the order declared in seeds.yaml
    grouped: dict[str, list[dict]] = {}
    for side, axes in sides.items():
        groups = []
        for axis in axes:
            genes = sorted(
                (g for g in placed.values() if g["axis"] == axis),
                key=lambda g: -g["degree"],
            )
            if genes:
                groups.append({"axis": axis, "genes": genes})
        grouped[side] = groups

    # --- claims that cross between the two sides --------------------------
    # Collect signed causal claims in both directions for every cross-side
    # ordered pair, so disagreement survives into the view.
    by_pair: dict[tuple[str, str], list[dict]] = {}
    for source, target, claim_id, data in snap.graph.edges(keys=True, data=True):
        if source not in placed or target not in placed:
            continue
        if placed[source]["side"] == placed[target]["side"]:
            continue
        if data.get("effect_sign") is None or not data.get("causal"):
            continue  # unsigned: a modification or binding asserts no direction
        if data.get("support_count", 0) < min_support:
            continue
        by_pair.setdefault((source, target), []).append(
            {
                "claim_id": claim_id,
                "predicate": data.get("predicate"),
                "effect_sign": data.get("effect_sign"),
                "negated": data.get("negated", False),
                "support_count": data.get("support_count", 0),
            }
        )

    links: list[dict] = []
    for (source, target), claims in by_pair.items():
        up = sum(c["support_count"] for c in claims if c["effect_sign"] == 1)
        down = sum(c["support_count"] for c in claims if c["effect_sign"] == -1)
        total = up + down
        if total == 0:
            continue
        minority = min(up, down)
        if minority == 0:
            basis = "undisputed"
        elif minority / total >= CONTESTED_MINORITY_SHARE:
            basis = "contested"
        else:
            basis = "dominant"
        links.append(
            {
                "from": {
                    "id": source,
                    "name": placed[source]["name"],
                    "axis": placed[source]["axis"],
                    "side": placed[source]["side"],
                },
                "to": {
                    "id": target,
                    "name": placed[target]["name"],
                    "axis": placed[target]["axis"],
                    "side": placed[target]["side"],
                },
                # A contested pair carries no direction. Saying "increases" here
                # because 51% of papers said so is the error this whole tool
                # exists to avoid.
                "direction": None if basis == "contested" else (1 if up > down else -1),
                "basis": basis,
                "support_up": up,
                "support_down": down,
                "claims": sorted(claims, key=lambda c: -c["support_count"]),
            }
        )

    links.sort(key=lambda link: -(link["support_up"] + link["support_down"]))
    truncated = len(links) > max_links
    return {
        "snapshot_id": snap.id,
        "filters": {
            "max_links": max_links,
            "min_support": min_support,
            "causal_only": True,
            "signed_only": True,
            "contested_minority_share": CONTESTED_MINORITY_SHARE,
        },
        "sides": grouped,
        "seeds_not_in_snapshot": missing,
        "links": links[:max_links],
        "truncated": truncated,
        "total_links": len(links),
        "note": (
            "Unsigned relations (binding, phosphorylation and other "
            "modifications) are excluded: they describe a mechanism, not a "
            "direction of effect. Contested pairs are shown without a direction."
        ),
    }


@router.get("/axes")
def axes(
    max_links: int = Query(80, ge=1, le=400),
    min_support: int = Query(1, ge=0, le=50),
):
    from nucleolis.api.main import snapshot

    return build_axes_view(snapshot(), max_links=max_links, min_support=min_support)
