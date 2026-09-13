"""Compare path orderings without changing the production ranking.

Production order is chosen by `Settings.path_ranking`. This module only reports
what each candidate ordering would do, so a ranking change is a measurement
rather than an opinion. No composite decimal score is produced: every variant is
a lexicographic key over interpretable fields.
"""
from __future__ import annotations


def weakest_support(path, papers: dict[str, int]) -> int:
    return min((papers.get(cid, 0) for cid in path.claim_ids), default=0)


def _current(path, ctx):
    return (-weakest_support(path, ctx["papers"]), path.belief_score is None, -(path.belief_score or 0), path.id)


def _belief_only(path, ctx):
    return (path.belief_score is None, -(path.belief_score or 0), path.id)


def _belief_removed(path, ctx):
    return (-weakest_support(path, ctx["papers"]), len(path.node_ids), path.id)


def _evidence_lexicographic(path, ctx):
    # Eligibility, then reviewed status, then distinct families, then opposition,
    # then a penalty for promiscuous intermediates, then the shorter path.
    return (
        0 if ctx["eligible"].get(path.id, True) else 1,
        0 if ctx["reviewed"].get(path.id, False) else 1,
        -ctx["families"].get(path.id, 0),
        1 if ctx["opposed"].get(path.id, False) else 0,
        -ctx["specificity"].get(path.id, 0.0),
        len(path.node_ids),
        path.id,
    )


VARIANTS = {"current": _current, "belief_only": _belief_only, "belief_removed": _belief_removed,
            "evidence_lexicographic": _evidence_lexicographic}


def order(paths, variant: str, ctx: dict) -> list[str]:
    return [p.id for p in sorted(paths, key=lambda path: VARIANTS[variant](path, ctx))]


def spearman(left: list[str], right: list[str]) -> float | None:
    """Rank correlation over the shared ids, or None when it is undefined."""
    shared = [i for i in left if i in right]
    n = len(shared)
    if n < 2:
        return None
    rank_left = {i: left.index(i) for i in shared}
    rank_right = {i: right.index(i) for i in shared}
    differences = sum((rank_left[i] - rank_right[i]) ** 2 for i in shared)
    return round(1 - (6 * differences) / (n * (n * n - 1)), 4)


def report(paths, *, papers: dict[str, int], families: dict[str, int] | None = None,
           opposed: dict[str, bool] | None = None, eligible: dict[str, bool] | None = None,
           reviewed: dict[str, bool] | None = None, specificity: dict[str, float] | None = None,
           display: int = 5) -> dict:
    ctx = {"papers": papers, "families": families or {}, "opposed": opposed or {},
           "eligible": eligible or {}, "reviewed": reviewed or {}, "specificity": specificity or {}}
    orders = {name: order(paths, name, ctx) for name in VARIANTS}
    baseline = orders["current"]
    shown = set(baseline[:display])
    comparisons = {}
    for name, ids in orders.items():
        if name == "current":
            continue
        candidate = set(ids[:display])
        first = next((i for i, (a, b) in enumerate(zip(baseline, ids)) if a != b), None)
        comparisons[name] = {
            "top_k_overlap": len(shown & candidate),
            "rank_correlation": spearman(baseline, ids),
            "enters_display": sorted(candidate - shown),
            "leaves_display": sorted(shown - candidate),
            "first_difference_at": first,
            "order": ids,
        }
    missing = sorted(key for key in ("families", "opposed", "eligible", "reviewed", "specificity") if not ctx[key])
    return {"paths": len(paths), "display": display, "current_order": baseline,
            "comparisons": comparisons, "features_not_supplied": missing}
