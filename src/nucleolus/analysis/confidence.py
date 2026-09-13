from nucleolus.analysis.adapter import AnalysisGraph
from nucleolus.schemas.simulation import EvidenceAssessment

BELIEF_CAVEAT = ("INDRA belief scores statement assembly, not correctness: on this corpus it does not "
                 "separate extraction faults from genuine disagreement, and tracks the extracting reader.")


def assess(graph: AnalysisGraph) -> EvidenceAssessment:
    refs = {s.statement_hash: s for e in graph.links for s in e.statement_refs}
    scored = [r.belief for r in refs.values() if r.belief is not None]
    limitations = ["Statement belief is not a treatment probability; publications are not independent studies.",
                   BELIEF_CAVEAT]
    if len(scored) != len(refs) or not refs:
        limitations.append("INDRA belief coverage is missing or incomplete.")
    if any(not e.statement_hashes for e in graph.evidence):
        limitations.append("Some evidence has no statement attribution; the known statement denominator is incomplete.")
    reviewed = sum(e.review_status == "approved" for e in graph.evidence)
    if reviewed < len(graph.evidence):
        limitations.append(f"{len(graph.evidence) - reviewed} evidence records are unreviewed machine extraction.")
    curated = sum(link.source_class in {"curated_database", "mixed"} for link in graph.links)
    machine_read = sum(link.source_class == "machine_read" for link in graph.links)
    multi_source = sum(len(link.sources) > 1 for link in graph.links)
    if graph.links and not curated:
        limitations.append("No claim here is supported by a curated database; all of it is machine-read text.")
    return EvidenceAssessment(unique_statement_count=len(refs), scored_statement_count=len(scored),
                              belief_coverage=len(scored) / len(refs) if refs else None,
                              weakest_belief=min(scored) if scored else None,
                              distinct_publication_count=len({e.publication_id for e in graph.evidence if e.publication_id}),
                              reviewed_evidence_count=reviewed,
                              curated_database_claims=curated, machine_read_claims=machine_read,
                              multi_source_claims=multi_source, limitations=limitations)
