"""Optional BEL representation. The Boolean executor is independent of PyBEL."""
import importlib
import os
from functools import lru_cache

from nucleolis import config
from nucleolis.analysis.adapter import AnalysisGraph


@lru_cache(maxsize=1)
def _library():
    # PyBEL/PyStow creates caches at import. Keep default caches in project data.
    os.environ.setdefault("PYSTOW_HOME", str(config.data_dir() / "library-cache"))
    os.environ.setdefault("PYSTOW_CONFIG_HOME", str(config.data_dir() / "library-config"))
    return importlib.import_module("pybel")


def available() -> bool:
    try:
        _library()
        return True
    except (ImportError, OSError, RuntimeError):
        return False


def to_bel(graph: AnalysisGraph, entities: dict):
    BELGraph = _library().BELGraph
    from pybel.dsl import Protein, BiologicalProcess, Abundance, activity

    bel = BELGraph(name="nucleolis reviewed analysis", version="1")
    bel.annotation_list["claim_id"] = {edge.id for edge in graph.links}
    bel.annotation_list["evidence_id"] = {item.id for item in graph.evidence}
    nodes = {}
    for entity_id in graph.entity_ids:
        entity = entities[entity_id]
        constructor = Protein if entity.get("entity_type") == "gene_protein" else BiologicalProcess if entity.get("entity_type") == "process" else Abundance
        namespace, identifier = entity_id.split(":", 1)
        nodes[entity_id] = constructor(namespace=namespace, identifier=identifier,
                                       name=entity.get("preferred_name") or entity_id)
        bel.add_node(nodes[entity_id])
    evidence = {e.id: e for e in graph.evidence}
    for edge in graph.links:
        mapping = graph.mappings[edge.id]
        if mapping.source_state not in {"activity", "abundance"} or mapping.target_state not in {"activity", "abundance"}:
            raise ValueError("BEL adapter requires an explicit activity/abundance mapping.")
        for eid in edge.evidence_ids:
            item = evidence[eid]
            if not item.publication_id or not item.publication_id.startswith("PMID:"):
                raise ValueError("BEL export requires real PMID citations; non-PubMed provenance is retained in the JSON graph.")
            add = bel.add_increases if edge.sign == 1 else bel.add_decreases
            add(nodes[edge.source], nodes[edge.target], citation=item.publication_id.split(":", 1)[1],
                evidence=item.quote, annotations={"claim_id": edge.id, "evidence_id": eid},
                source_modifier=activity() if mapping.source_state == "activity" else None,
                target_modifier=activity() if mapping.target_state == "activity" else None,
                belief_score=edge.belief_score, statement_hashes=[s.statement_hash for s in edge.statement_refs])
    return bel
