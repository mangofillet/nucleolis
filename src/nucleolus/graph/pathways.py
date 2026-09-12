"""Layered pathway search: one source, bounded routes, one row per target.

The shape the UI needs is not a ball of nodes - it is a flow:

    SOURCE            ACTS THROUGH              TARGET
    TBK1      ->      OPTN, SQSTM1      ->      MAPT, TARDBP, ...

Two rules from HANDOVER.md govern the ranking:

  s7  Rank by the thinnest step, never the sum. The last hop into a hub can
      carry thousands of sentences while the source-specific first step carries
      five. The claim rests on those five.

  s7  Penalise promiscuous intermediates: specificity = 1/log10(degree). A hub
      is a good destination and a terrible intermediate, because everything
      routes through it and it therefore discriminates nothing.

  s7  Collapse to one row per (target, direction). This is the single biggest
      legibility win - in the reference system it took 113,916 paths to 72.
"""
from __future__ import annotations

from .queries import MAX_SIGNED_HOPS, Snapshot

# Never enumerate more than this many candidate routes before ranking.
CANDIDATE_BUDGET = 4000


def _leg_claims(snapshot: Snapshot, source: str, target: str, causal_only: bool = True):
    """Every claim asserting source -> target, as claim views."""
    out = []
    for edge_source, edge_target, claim_id, data in snapshot.graph.edges(
        [source], keys=True, data=True
    ):
        if edge_source != source or edge_target != target:
            continue
        if causal_only and not data.get("causal"):
            continue
        if data.get("negated"):
            continue
        out.append(snapshot.claim_view(claim_id))
    return out


def _leg_weight(claims) -> int:
    """Distinct supporting papers behind a leg, taking the best-supported claim.

    Deliberately not a sum across claims: two opposing claims on the same leg
    are a disagreement, not double the evidence.
    """
    return max((c["n_papers"] for c in claims), default=0)


# A leg whose minority direction holds less than this share of the supporting
# papers is treated as directional, with the minority still reported. Above it,
# the leg is contested and carries no direction at all.
MINORITY_TOLERANCE = 0.25


def _leg_sign(claims):
    """Direction of a leg, with the basis on which it was decided.

    Returns (sign, basis) where basis is one of:
      undisputed - every signed claim agrees
      dominant   - disagreement exists but the minority is below tolerance
      contested  - genuine disagreement; NO direction is asserted
      unsigned   - nothing here carries a direction (binding, modification)

    Support and dispute are never netted into a single number. The minority
    count travels with the result so a reader always sees what was set aside.
    """
    pos = sum(c["n_papers"] for c in claims if c["effect_sign"] == 1)
    neg = sum(c["n_papers"] for c in claims if c["effect_sign"] == -1)
    if pos == 0 and neg == 0:
        return None, "unsigned"
    if pos == 0:
        return -1, "undisputed"
    if neg == 0:
        return 1, "undisputed"
    minority = min(pos, neg) / (pos + neg)
    if minority < MINORITY_TOLERANCE:
        return (1 if pos > neg else -1), "dominant"
    return None, "contested"


def _leg_contest(claims):
    pos = sum(c["n_papers"] for c in claims if c["effect_sign"] == 1)
    neg = sum(c["n_papers"] for c in claims if c["effect_sign"] == -1)
    if pos > 0 and neg > 0:
        return {"pos": pos, "neg": neg}
    return None


def pathways(
    snapshot: Snapshot,
    source_id: str,
    max_hops: int = MAX_SIGNED_HOPS,
    max_targets: int = 24,
    min_papers: int = 1,
    target_id: str | None = None,
) -> dict:
    """Bounded layered routes out of one source."""
    if source_id not in snapshot.graph:
        raise KeyError(source_id)

    max_hops = min(max_hops, MAX_SIGNED_HOPS)

    # --- enumerate bounded routes over signed causal edges ----------------
    routes: list[list[str]] = []
    truncated = False

    def walk(node: str, trail: list[str]) -> None:
        nonlocal truncated
        if len(trail) - 1 >= max_hops or len(routes) >= CANDIDATE_BUDGET:
            return
        for _, neighbour, _key, data in snapshot.graph.edges(
            [node], keys=True, data=True
        ):
            if not data.get("causal") or data.get("negated"):
                continue
            if neighbour in trail:  # simple paths only
                continue
            if data.get("support_count", 0) < min_papers:
                continue
            extended = trail + [neighbour]
            if len(routes) >= CANDIDATE_BUDGET:
                truncated = True
                return
            routes.append(extended)
            walk(neighbour, extended)

    walk(source_id, [source_id])

    if target_id:
        routes = [r for r in routes if r[-1] == target_id]

    # --- score each route, then keep the best one per target --------------
    best: dict[str, dict] = {}
    for route in routes:
        destination = route[-1]
        if destination == source_id:
            continue

        legs = []
        weakest = None
        specificity = 1.0
        ok = True
        for index in range(len(route) - 1):
            claims = _leg_claims(snapshot, route[index], route[index + 1])
            if not claims:
                ok = False
                break
            papers = _leg_weight(claims)
            weakest = papers if weakest is None else min(weakest, papers)
            sign, basis = _leg_sign(claims)
            legs.append(
                {
                    "from": route[index],
                    "to": route[index + 1],
                    "claims": claims,
                    "papers": papers,
                    "sign": sign,
                    "sign_basis": basis,
                    "contested": _leg_contest(claims),
                }
            )
        if not ok or weakest is None:
            continue

        for intermediate in route[1:-1]:
            specificity *= snapshot.specificity.get(intermediate, 1.0)

        # Sign of the whole route is the product of its legs. A single unsigned
        # or contested leg makes the route direction unknown - never guessed.
        implied = 1
        implied_basis = "undisputed"
        for leg in legs:
            if leg["sign"] is None:
                implied = None
                implied_basis = leg["sign_basis"]  # contested or unsigned
                break
            implied *= leg["sign"]
            if leg["sign_basis"] == "dominant":
                implied_basis = "dominant"

        score = weakest * specificity
        candidate = {
            "target_id": destination,
            "hops": len(route) - 1,
            "nodes": route,
            "legs": legs,
            "weakest_leg_papers": weakest,
            "specificity": round(specificity, 4),
            "score": round(score, 3),
            "implied_direction": implied,
            "direction_basis": implied_basis,
        }
        current = best.get(destination)
        # Prefer the higher score; break ties toward the shorter route.
        if current is None or (score, -len(route)) > (current["score"], -len(current["nodes"])):
            best[destination] = candidate

    ranked = sorted(best.values(), key=lambda r: -r["score"])
    targets_truncated = len(ranked) > max_targets
    ranked = ranked[:max_targets]

    # --- assemble the layered node set ------------------------------------
    # A node that carries traffic onward is an intermediate, even if some other
    # route also terminates at it. Using max() here emptied the middle column
    # entirely, because most intermediates are also targets in their own right.
    intermediates: set[str] = set()
    terminals: set[str] = set()
    for route in ranked:
        for position, node in enumerate(route["nodes"]):
            if position == 0:
                continue
            if position < route["hops"]:
                intermediates.add(node)
            else:
                terminals.add(node)

    layer_of: dict[str, int] = {source_id: 0}
    for node in intermediates:
        layer_of[node] = 1
    for node in terminals:
        if node not in intermediates:
            layer_of[node] = 2

    nodes = []
    for node_id, layer in layer_of.items():
        entity = snapshot.entities[node_id]
        nodes.append(
            {
                "id": node_id,
                "name": entity.get("preferred_name") or node_id,
                "long_name": entity.get("long_name"),
                "layer": layer,
                "degree": snapshot.graph.degree(node_id),
                "specificity": round(snapshot.specificity.get(node_id, 1.0), 4),
            }
        )
    nodes.sort(key=lambda n: (n["layer"], -n["degree"]))

    # deduplicate legs across routes, keeping the claim detail
    legs: dict[tuple[str, str], dict] = {}
    for route in ranked:
        for leg in route["legs"]:
            legs.setdefault((leg["from"], leg["to"]), leg)

    return {
        "snapshot_id": snapshot.id,
        "source": {
            "id": source_id,
            "name": snapshot.entities[source_id].get("preferred_name"),
            "degree": snapshot.graph.degree(source_id),
        },
        "filters": {
            "max_hops": max_hops,
            "max_targets": max_targets,
            "min_papers": min_papers,
            "target_id": target_id,
            "ranking": "weakest leg (papers) x product of intermediate specificity",
            "signed_hop_cap": MAX_SIGNED_HOPS,
        },
        "layers": ["source", "acts through", "target"],
        "nodes": nodes,
        "legs": list(legs.values()),
        "routes": ranked,
        "truncation": {
            "candidates_truncated": truncated,
            "targets_truncated": targets_truncated,
            "candidate_budget": CANDIDATE_BUDGET,
            "note": "One route per target: the best-scoring one. Other routes to "
                    "the same target exist and are not shown. A bounded search "
                    "finding nothing is not evidence that nothing is there.",
        },
    }
