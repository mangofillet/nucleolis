from nucleolus.analysis.adapter import AnalysisGraph
from nucleolus.schemas.simulation import EvidenceAssessment


def assess(graph: AnalysisGraph) -> EvidenceAssessment:
    refs = {s.statement_hash: s for e in graph.links for s in e.statement_refs}
    scored = [r.belief for r in refs.values() if r.belief is not None]
    limitations = ["Statement belief is not a treatment probability; publications are not independent studies."]
    if len(scored) != len(refs) or not refs:
        limitations.append("INDRA belief coverage is missing or incomplete.")
    if any(not e.statement_hashes for e in graph.evidence):
        limitations.append("Some evidence has no statement attribution; the known statement denominator is incomplete.")
    return EvidenceAssessment(unique_statement_count=len(refs), scored_statement_count=len(scored),
                              belief_coverage=len(scored) / len(refs) if refs else None,
                              weakest_belief=min(scored) if scored else None,
                              distinct_publication_count=len({e.publication_id for e in graph.evidence if e.publication_id}),
                              reviewed_evidence_count=len(graph.evidence), limitations=limitations)
