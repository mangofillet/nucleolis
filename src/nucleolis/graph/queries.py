"""Bounded in-memory graph over a validated snapshot.

EXECUTION_PLAN.md s6: every graph result identifies the snapshot, the applied
filters, whether it was truncated, and the supporting evidence IDs. Truncation is
always reported rather than silently applied.
"""
from __future__ import annotations

import json
import math
import pathlib

import networkx as nx

from nucleolis import config

# Hard ceilings from EXECUTION_PLAN.md s6. Requests may ask for less, never more.
HARD_MAX_NODES = 800
HARD_MAX_EDGES = 2000
DEFAULT_NODES = 150
MAX_PATHS = 5
# HANDOVER.md s10: INDRA belief runs 0.37-0.66. Compounding three of those,
# before parse error and sign-composition error, is "noise wearing a decimal
# point". Signed claims stop at 2 hops; hop 3 is unsigned reachability only.
MAX_SIGNED_HOPS = 2
MAX_HOPS = 4

CAUSAL_PREDICATES = {"activates", "inhibits", "increases_amount", "decreases_amount"}


class SnapshotNotFound(Exception):
    pass


class Snapshot:
    """Immutable, read-only view of one validated snapshot."""

    def __init__(self, payload: dict, path: pathlib.Path) -> None:
        self.path = path
        self.id = payload["id"]
        self.schema_version = payload["schema_version"]
        self.created_at = payload["created_at"]
        self.checksum = payload.get("checksum")
        self.coverage = payload.get("coverage", {})
        self.limitations = payload.get("limitations", [])
        self.license_note = payload.get("license_note")
        self.query = payload.get("query", {})

        self.entities = {e["id"]: e for e in payload["entities"]}
        self.contexts = {c["id"]: c for c in payload["contexts"]}
        self.claims = {c["id"]: c for c in payload["claims"]}
        self.documents = {d["id"]: d for d in payload["documents"]}
        self.evidence = {e["id"]: e for e in payload["evidence"]}

        self.provenance_by_evidence: dict[str, list[dict]] = {}
        for row in payload["provenance"]:
            self.provenance_by_evidence.setdefault(row["evidence_id"], []).append(row)

        self.evidence_by_claim: dict[str, list[dict]] = {}
        for row in payload["evidence"]:
            self.evidence_by_claim.setdefault(row["claim_id"], []).append(row)

        self.graph = nx.MultiDiGraph()
        for entity in payload["entities"]:
            self.graph.add_node(entity["id"], **entity)
        for claim in payload["claims"]:
            self.graph.add_edge(
                claim["subject_id"],
                claim["object_id"],
                key=claim["id"],
                claim_id=claim["id"],
                predicate=claim["predicate"],
                effect_sign=claim["effect_sign"],
                causal=claim.get("causal", False),
                negated=claim["negated"],
                support_count=claim["support_count"],
            )

        # name -> ids, for search
        # HANDOVER.md s7: a hub is a good destination and a terrible
        # intermediate. specificity = 1/log10(degree) penalises routes through
        # promiscuous nodes, which otherwise dominate every path result.
        self.specificity: dict[str, float] = {}
        for node in self.graph.nodes():
            degree = self.graph.degree(node)
            self.specificity[node] = 1.0 / math.log10(degree) if degree > 10 else 1.0

        self._by_name: dict[str, list[str]] = {}
        for entity in payload["entities"]:
            name = (entity.get("preferred_name") or "").upper()
            if name:
                self._by_name.setdefault(name, []).append(entity["id"])

    # -- lookups ----------------------------------------------------------

    @staticmethod
    def _fold(value: str) -> str:
        """Strip punctuation for matching: 'CSF-1' and 'CSF1' are one symbol.

        Literature writes gene symbols inconsistently (CSF-1 / CSF1, IL-34 /
        IL34, PGC-1alpha / PPARGC1A). ground.py already resolves HGNC aliases
        and previous symbols during the pipeline, but that never reached this
        lookup, so a hyphen alone made a present gene unfindable.
        """
        return "".join(ch for ch in value.upper() if ch.isalnum())

    def search_nodes(self, query: str, limit: int = 20) -> list[dict]:
        needle = query.strip().upper()
        folded = self._fold(query)
        if not needle:
            return []
        exact, prefix, contains = [], [], []
        for entity in self.entities.values():
            name = (entity.get("preferred_name") or "").upper()
            long_name = (entity.get("long_name") or "").upper()
            if not name:
                continue
            if name == needle or (folded and self._fold(name) == folded):
                exact.append(entity)
            elif name.startswith(needle):
                prefix.append(entity)
            elif needle in name or needle in long_name:
                contains.append(entity)
        ordered = exact + prefix + contains
        results = []
        for entity in ordered[:limit]:
            record = dict(entity)
            record["degree"] = self.graph.degree(entity["id"]) if entity["id"] in self.graph else 0
            results.append(record)
        return results

    def claim_view(self, claim_id: str) -> dict:
        # Local import: nucleolis.analysis imports this module, so the package edge stays one-way.
        from nucleolis.analysis.sources import classify

        claim = self.claims[claim_id]
        subject = self.entities[claim["subject_id"]]
        obj = self.entities[claim["object_id"]]
        provenance = classify(claim.get("source_counts"))
        return {
            "source_class": provenance["source_class"],
            "source_class_label": provenance["source_class_label"],
            "curated_sources": provenance["database_sources"],
            "claim_id": claim["id"],
            "subject": {"id": subject["id"], "name": subject.get("preferred_name")},
            "predicate": claim["predicate"],
            "object": {"id": obj["id"], "name": obj.get("preferred_name")},
            "effect_sign": claim["effect_sign"],
            "causal": claim.get("causal", False),
            "negated": claim["negated"],
            "epistemic_status": claim["epistemic_status"],
            "context_id": claim["context_id"],
            "support_count": claim["support_count"],
            "n_papers": claim.get("n_papers", claim["support_count"]),
            "n_primary": claim.get("n_primary"),
            "n_retracted": claim.get("n_retracted", 0),
            "n_sentences": claim.get("n_sentences"),
            "sole_support_retracted": claim.get("sole_support_retracted", False),
            "earliest_publication_date": claim.get("earliest_publication_date"),
            "evidence_count": len(claim["evidence_ids"]),
            # When the snapshot was built with an evidence cap, the stored list
            # is a sample. Reporting only its length would understate the trail
            # without saying so, so the true total travels with it.
            "evidence_total": claim.get("evidence_total", len(claim["evidence_ids"])),
            "evidence_capped": claim.get("evidence_capped", False),
            "evidence_ids": claim["evidence_ids"],
            "source_statement_hash": claim.get("source_statement_hash"),
            "source_counts": claim.get("source_counts"),
            "indra_statement_type": (claim.get("qualifiers_json") or {}).get(
                "indra_statement_type"
            ),
        }

    # -- neighbourhood ----------------------------------------------------

    def neighborhood(
        self,
        node_id: str,
        hops: int = 1,
        max_nodes: int = DEFAULT_NODES,
        causal_only: bool = False,
        min_support: int = 0,
        edge_scope: str = "incident",
    ) -> dict:
        if node_id not in self.graph:
            raise KeyError(node_id)

        max_nodes = min(max_nodes, HARD_MAX_NODES)
        undirected = self.graph.to_undirected(as_view=True)

        # breadth-first, ordered by support so truncation keeps the best-evidenced
        selected = [node_id]
        seen = {node_id}
        frontier = [node_id]
        truncated_nodes = False
        for _ in range(hops):
            candidates = []
            for current in frontier:
                for neighbor in undirected.neighbors(current):
                    if neighbor in seen:
                        continue
                    support = max(
                        (
                            data.get("support_count", 0)
                            for _, _, data in self.graph.edges(neighbor, data=True)
                        ),
                        default=0,
                    )
                    candidates.append((support, neighbor))
            candidates.sort(reverse=True)
            next_frontier = []
            for _, neighbor in candidates:
                if neighbor in seen:
                    continue
                if len(selected) >= max_nodes:
                    truncated_nodes = True
                    break
                seen.add(neighbor)
                selected.append(neighbor)
                next_frontier.append(neighbor)
            frontier = next_frontier
            if truncated_nodes:
                break

        node_set = set(selected)
        edges = []
        truncated_edges = False
        for source, target, claim_id, data in self.graph.edges(keys=True, data=True):
            if source not in node_set or target not in node_set:
                continue
            # "incident" keeps the view readable: only claims that touch the centre.
            # "all" additionally shows claims among the neighbours, which for a
            # dense neighbourhood is hundreds of edges.
            if edge_scope == "incident" and node_id not in (source, target):
                continue
            if causal_only and not data.get("causal"):
                continue
            if data.get("support_count", 0) < min_support:
                continue
            if len(edges) >= HARD_MAX_EDGES:
                truncated_edges = True
                break
            edges.append(self.claim_view(claim_id))

        return {
            "snapshot_id": self.id,
            "center": node_id,
            "filters": {
                "hops": hops,
                "max_nodes": max_nodes,
                "causal_only": causal_only,
                "min_support": min_support,
                "edge_scope": edge_scope,
            },
            "nodes": [
                {
                    "id": entity_id,
                    "name": self.entities[entity_id].get("preferred_name"),
                    "long_name": self.entities[entity_id].get("long_name"),
                    "entity_type": self.entities[entity_id].get("entity_type"),
                    "taxon_id": self.entities[entity_id].get("taxon_id"),
                    "is_center": entity_id == node_id,
                }
                for entity_id in selected
            ],
            "edges": edges,
            "truncation": {
                "nodes_truncated": truncated_nodes,
                "edges_truncated": truncated_edges,
                "hard_max_nodes": HARD_MAX_NODES,
                "hard_max_edges": HARD_MAX_EDGES,
            },
        }

    # -- paths -------------------------------------------------------------

    def paths(
        self,
        source_id: str,
        target_id: str,
        max_hops: int = MAX_HOPS,
        max_paths: int = MAX_PATHS,
        causal_only: bool = True,
    ) -> dict:
        if source_id not in self.graph:
            raise KeyError(source_id)
        if target_id not in self.graph:
            raise KeyError(target_id)

        max_hops = min(max_hops, MAX_HOPS)
        max_paths = min(max_paths, MAX_PATHS)
        signed_capped = False
        if causal_only and max_hops > MAX_SIGNED_HOPS:
            max_hops = MAX_SIGNED_HOPS
            signed_capped = True

        if causal_only:
            allowed = nx.DiGraph()
            allowed.add_nodes_from(self.graph.nodes())
            for source, target, data in self.graph.edges(data=True):
                if data.get("causal") and not data.get("negated"):
                    allowed.add_edge(source, target)
            search_graph = allowed
        else:
            search_graph = nx.DiGraph(self.graph)

        # Enumerate a bounded candidate pool, then rank - taking the first N in
        # traversal order funnels every result through whichever hub comes first.
        candidates = []
        truncated = False
        try:
            for node_path in nx.all_simple_paths(
                search_graph, source_id, target_id, cutoff=max_hops
            ):
                candidates.append(node_path)
                if len(candidates) >= 400:
                    truncated = True
                    break
        except nx.NetworkXNoPath:
            candidates = []

        def score(node_path):
            """Rank by the thinnest step, discounted by intermediate promiscuity."""
            intermediates = node_path[1:-1]
            thinnest = None
            for index in range(len(node_path) - 1):
                best = 0
                for a, b, _k, data in self.graph.edges([node_path[index]], keys=True, data=True):
                    if b != node_path[index + 1] or not data.get("causal"):
                        continue
                    best = max(best, data.get("support_count", 0))
                thinnest = best if thinnest is None else min(thinnest, best)
            thinnest = thinnest or 0
            penalty = 1.0
            for node in intermediates:
                penalty *= self.specificity.get(node, 1.0)
            return (thinnest * penalty, -len(node_path))

        candidates.sort(key=score, reverse=True)
        if len(candidates) > max_paths:
            truncated = True
        found = candidates[:max_paths]

        results = []
        for node_path in found:
            steps = []
            for index in range(len(node_path) - 1):
                source, target = node_path[index], node_path[index + 1]
                step_claims = []
                for edge_source, edge_target, claim_id, data in self.graph.edges(
                    [source], keys=True, data=True
                ):
                    if edge_source != source or edge_target != target:
                        continue
                    if not data.get("causal") or data.get("negated"):
                        continue
                    step_claims.append(self.claim_view(claim_id))
                steps.append(
                    {
                        "from": source,
                        "to": target,
                        "from_name": self.entities[source].get("preferred_name"),
                        "to_name": self.entities[target].get("preferred_name"),
                        "claims": step_claims,
                    }
                )
            results.append(
                {
                    "nodes": node_path,
                    "hops": len(node_path) - 1,
                    "steps": steps,
                }
            )

        return {
            "snapshot_id": self.id,
            "source_id": source_id,
            "target_id": target_id,
            "mode": "causal_only" if causal_only else "broader_relational",
            "filters": {
                "max_hops": max_hops,
                "max_paths": max_paths,
                "signed_hop_cap_applied": signed_capped,
                "ranking": "thinnest supporting step, discounted by intermediate specificity",
            },
            "paths": results,
            "truncation": {
                "paths_truncated": truncated,
                "note": "More paths may exist beyond max_paths; absence here is not "
                        "evidence of absence.",
            },
        }

    # -- evidence ----------------------------------------------------------

    def evidence_for_claim(self, claim_id: str, offset: int = 0, limit: int = 25) -> dict:
        if claim_id not in self.claims:
            raise KeyError(claim_id)
        rows = self.evidence_by_claim.get(claim_id, [])
        page = rows[offset : offset + limit]
        items = []
        for row in page:
            document = self.documents.get(row["document_id"]) if row["document_id"] else None
            items.append(
                {
                    "evidence_id": row["id"],
                    "quote": row["quote"],
                    "negated": row["negated"],
                    "experimental_basis": row["experimental_basis"],
                    "source_evidence_code": row["source_evidence_code"],
                    "review_status": row["review_status"],
                    "context": self.contexts.get(row["context_id"]),
                    "document": document,
                    "link": _document_link(document),
                    "provenance": self.provenance_by_evidence.get(row["id"], []),
                }
            )
        claim = self.claims[claim_id]
        return {
            "snapshot_id": self.id,
            "claim": self.claim_view(claim_id),
            "total": len(rows),
            # `total` counts what this snapshot stores. When a cap was applied at
            # build time the claim is supported by more records than are held
            # here, and a reader must be able to see that.
            "total_before_cap": claim.get("evidence_total", len(rows)),
            "evidence_capped": claim.get("evidence_capped", False),
            "offset": offset,
            "limit": limit,
            "evidence": items,
        }

    def evidence_for_node(self, node_id: str, offset: int = 0, limit: int = 25) -> dict:
        if node_id not in self.graph:
            raise KeyError(node_id)
        claim_ids = [
            claim_id
            for _, _, claim_id in self.graph.edges([node_id], keys=True)
        ] + [
            claim_id
            for _, _, claim_id in self.graph.in_edges([node_id], keys=True)
        ]
        claim_ids = sorted(
            set(claim_ids), key=lambda cid: -self.claims[cid]["support_count"]
        )
        page = claim_ids[offset : offset + limit]
        return {
            "snapshot_id": self.id,
            "node": {
                "id": node_id,
                "name": self.entities[node_id].get("preferred_name"),
            },
            "total": len(claim_ids),
            "offset": offset,
            "limit": limit,
            "claims": [self.claim_view(cid) for cid in page],
        }


def _document_link(document):
    if not document:
        return None
    if document.get("pmid"):
        return "https://pubmed.ncbi.nlm.nih.gov/" + document["pmid"] + "/"
    if document.get("pmcid"):
        return "https://www.ncbi.nlm.nih.gov/pmc/articles/" + document["pmcid"] + "/"
    if document.get("doi"):
        return "https://doi.org/" + document["doi"]
    return None


def load_snapshot(snapshot_id: str | None = None) -> Snapshot:
    snapshots_dir = config.data_dir() / "snapshots"
    if snapshot_id is None:
        current = snapshots_dir / "CURRENT"
        if not current.exists():
            raise SnapshotNotFound("no CURRENT snapshot - run the build stage first")
        snapshot_id = current.read_text(encoding="utf-8").strip()
    path = snapshots_dir / (snapshot_id + ".json")
    if not path.exists():
        raise SnapshotNotFound("snapshot not found: " + str(path))
    return Snapshot(json.loads(path.read_text(encoding="utf-8")), path)
