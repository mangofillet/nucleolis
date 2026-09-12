from __future__ import annotations

import hashlib
import time

from nucleolus.analysis.adapter import AnalysisGraph
from nucleolus.schemas.simulation import DirectionResult, GroundedQuery, Limits, PathAnalysis, SignedPath


def analyze(graph: AnalysisGraph, query: GroundedQuery, desired: int | None,
            limits: Limits | None = None) -> PathAnalysis:
    limits = limits or Limits()
    deadline = time.monotonic() + limits.graph_seconds
    adjacency = {}
    for link in graph.links:
        adjacency.setdefault(link.source, []).append(link)
    paths, directions = [], {}
    examined, truncated = 0, False

    def walk(node, visited, claims, evidence_ids, sign, target_state, scores):
        nonlocal examined, truncated
        if len(claims) >= limits.max_hops:
            return
        for edge in sorted(adjacency.get(node, []), key=lambda e: e.id):
            if examined >= limits.candidate_budget or time.monotonic() >= deadline:
                truncated = True
                return
            examined += 1
            if edge.target in visited:
                continue
            mapping = graph.mappings[edge.id]
            if target_state is not None and target_state != mapping.source_state:
                continue
            ns = sign * edge.sign
            nc, nv = claims + [edge.id], visited + [edge.target]
            ne = sorted(set(evidence_ids) | set(edge.evidence_ids))
            nb = scores + [edge.belief_score]
            directions.setdefault(edge.target, set()).add(ns)
            if edge.target == query.target_id and (query.target_state_id is None or query.target_state_id == mapping.target_state):
                pid = "path_" + hashlib.sha256("|".join(nc).encode()).hexdigest()[:20]
                paths.append(SignedPath(id=pid, node_ids=nv, claim_ids=nc, evidence_ids=ne,
                                        implied_direction=ns,
                                        belief_score=min(nb) if all(s is not None for s in nb) else None))
            walk(edge.target, nv, nc, ne, ns, mapping.target_state, nb)
            if truncated:
                return

    walk(query.source_id, [query.source_id], [], [], query.intervention_direction, query.source_state_id, [])
    effects = directions.get(query.target_id, set())
    category = ("insufficient_evidence" if not effects else "not_requested" if desired is None else
                "conflicting" if len(effects) == 2 else "supportive_only" if desired in effects else "opposing_only")
    # Stable interleaving makes both signs visible even with the five-path display cap.
    buckets = {sign: sorted((p for p in paths if p.implied_direction == sign),
                           key=lambda p: (p.belief_score is None, -(p.belief_score or 0), p.id)) for sign in (-1, 1)}
    ordered = []
    for i in range(max(len(b) for b in buckets.values())):
        for sign in (-1, 1):
            if i < len(buckets[sign]):
                ordered.append(buckets[sign][i])
    return PathAnalysis(category=category, completion="truncated" if truncated else "complete_within_limits",
                        paths=ordered[:limits.display_paths],
                        directions=[DirectionResult(node_id=node, possible_directions=sorted(values))
                                    for node, values in sorted(directions.items())],
                        examined_candidates=examined, total_paths=len(paths),
                        display_paths_omitted=max(0, len(paths) - limits.display_paths))


def exclusion_effect(before: PathAnalysis, after: PathAnalysis) -> str:
    if before.completion != "complete_within_limits" or after.completion != "complete_within_limits":
        return "indeterminate"
    if before.total_paths and not after.total_paths:
        return "sole_support_lost"
    if before.category == "conflicting" and after.category in {"supportive_only", "opposing_only"}:
        return "conflict_resolved"
    if after.total_paths < before.total_paths:
        return "support_reduced"
    return "no_change"
