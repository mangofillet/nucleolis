"""Fictional software fixture. Never used as fallback for a live provider failure."""
from nucleolis.graph.queries import Snapshot
from nucleolis.schemas.simulation import (
    BooleanManifest, BooleanVariable, ClaimMapping, ClaudeSynthesis, EntityMention,
    EvidenceReview, ParsedQuery, ReviewManifest, Rule, StatementRef,
)

DEMO_QUERY = "What happens to Reporter C if I knock out Switch A?"


def fixture():
    ids = ["DEMO:A", "DEMO:B", "DEMO:C"]
    names = ["Switch A", "Mediator B", "Reporter C"]
    entities = [dict(id=i, namespace="DEMO", accession=i[-1], entity_type="process",
                     preferred_name=n, long_name="Fictional Boolean fixture variable", taxon_id=None)
                for i, n in zip(ids, names)]
    claims, evidence, documents, reviews, mappings, statements = [], [], [], [], [], []
    for cid, source, target, sign in [("demo_ab", ids[0], ids[1], 1), ("demo_bc", ids[1], ids[2], -1)]:
        eid, doc, h = "e_" + cid, "DEMO-PAPER:" + cid, "stmt_" + cid
        claims.append(dict(id=cid, subject_id=source, object_id=target,
                           predicate="activates" if sign == 1 else "inhibits", effect_sign=sign,
                           causal=True, negated=False, context_id="demo_context", support_count=1,
                           evidence_ids=[eid], document_ids=[doc]))
        documents.append(dict(id=doc, pmid=None, pmcid=None, doi=None, retraction_status="not_retracted", is_primary=None))
        evidence.append(dict(id=eid, claim_id=cid, document_id=doc,
                             quote=f"FICTIONAL TEST ASSERTION: {source} {'activates' if sign == 1 else 'inhibits'} {target}.",
                             negated=False, context_id="demo_context", source_evidence_code="synthetic_fixture",
                             review_status="synthetic"))
        reviews.append(EvidenceReview(evidence_id=eid, claim_id=cid, approved=True, source_checked=True,
                                      context_compatible=True, reviewer="software_fixture_not_scientific_review",
                                      statement_hashes=[h]))
        mappings.append(ClaimMapping(claim_id=cid, source_state="activity", target_state="activity",
                                     assumption="Fictional binary activity variables; not a biological assertion."))
        statements.append(StatementRef(statement_hash=h, statement_type="Activation" if sign == 1 else "Inhibition", belief=0.8))
    snap = Snapshot(dict(id="synthetic_sandwich_v1", schema_version=1, created_at="2026-09-12T00:00:00Z",
                         checksum="synthetic:fixture_v1", entities=entities, claims=claims, evidence=evidence,
                         documents=documents, contexts=[{"id": "demo_context"}], provenance=[]), path=None)
    review = ReviewManifest(version="synthetic_review_v1", snapshot_id=snap.id, snapshot_checksum=snap.checksum,
                            context_id="demo_context", synthetic=True, selected_entity_ids=ids,
                            reviews=reviews, mappings=mappings, statements=statements)
    model = BooleanManifest(id="synthetic_boolean_v1", version="1", review_version=review.version,
                            snapshot_checksum=snap.checksum, context_id="demo_context",
                            reviewer="software_fixture_not_scientific_review", synthetic=True, readout="c",
                            variables=[BooleanVariable(id=i.lower(), entity_id="DEMO:" + i, state="activity", initial=1 if i != "C" else 0) for i in "ABC"],
                            rules=[Rule(id="rule_a", target="a", operation="identity", regulators=["a"], assumption="A retains its initial value unless clamped."),
                                   Rule(id="rule_b", target="b", operation="identity", regulators=["a"], claim_ids=["demo_ab"], assumption="B copies A."),
                                   Rule(id="rule_c", target="c", operation="not", regulators=["b"], claim_ids=["demo_bc"], assumption="C is NOT B.")],
                            assumptions=["Fictional three-variable software model; no biomedical validation.", "Logical steps have no physical duration."])
    return snap, review, model


class DemoParser:
    model = "synthetic_fixture_parser"

    async def parse(self, question, entity_catalog):
        if question.strip() != DEMO_QUERY:
            return ParsedQuery(source_entity=None, target_entity=None, query_intent="unsupported",
                               intervention="unspecified", desired_readout_direction=None, context_text=None,
                               clarification_reason="The synthetic fixture accepts only its displayed example question.")
        return ParsedQuery(source_entity=EntityMention(mention="Switch A", candidate_id="DEMO:A", resolution="matched"),
                           target_entity=EntityMention(mention="Reporter C", candidate_id="DEMO:C", resolution="matched"),
                           query_intent="intervention", intervention="knockout", desired_readout_direction=None,
                           context_text=None, clarification_reason=None)


class DemoScientist:
    model = "synthetic_fixture_synthesis"

    async def synthesize(self, bundle):
        return ClaudeSynthesis(biological_rationale=[],
                               confidence_assessment="Synthetic software fixture; example scores are invented test inputs, not scientific confidence.",
                               assumptions=["This draft is a fixture, not a Claude response."],
                               limitations=["No biological interpretation or wet-lab protocol is supported by fictional variables."],
                               validation_protocol=None)
