"""Deterministic corroboration categories. Python decides; no LLM reclassifies.

A distinct publication family adds qualifying evidence only when the paper is not
retracted, both entities are matched, stance and direction agree, it reports a
primary experiment, context is matched (or partial when allowed), and the passage
passes the review policy. Resolving a publication INDRA already cites is
cross-indexing, never corroboration.
"""
from __future__ import annotations

from nucleolus.corroboration import identity
from nucleolus.schemas.corroboration import AmassDocumentMetadata, ClaimCorroboration, CorroboratingPassage

BOUNDED_SEARCH = "Search is bounded; absence of an additional record is not evidence against the claim."
FAMILY_LIMIT = "Publication families are bibliographic; overlapping cohorts or shared datasets are not detected."


def passes_review(passage: CorroboratingPassage, policy: str) -> bool:
    return passage.review_status == "approved" or (
        policy == "allow_labelled_unreviewed" and passage.review_status == "unreviewed")


def qualifying_stance(passage, document, policy, allow_partial_context=False):
    """'support', 'oppose', or None when the passage cannot count."""
    if document is None or document.is_retracted is True or not passes_review(passage, policy):
        return None
    if passage.subject_match != "matched" or passage.object_match != "matched":
        return None
    if passage.evidence_role != "primary_experiment":
        return None
    if passage.context_match not in ({"matched", "partial"} if allow_partial_context else {"matched"}):
        return None
    if passage.stance == "supports" and passage.direction_match == "matched":
        return "support"
    if passage.stance == "opposes" and passage.direction_match == "opposite":
        return "oppose"
    return None


def categorize(claim_id: str, indra_keys: set[str], documents: list[AmassDocumentMetadata],
               passages: list[CorroboratingPassage], *, source_classes: list[str], searched_queries: list[str],
               searched: bool, truncated: bool = False, unavailable: bool = False,
               policy: str = "require_approval", allow_partial_context: bool = False) -> ClaimCorroboration:
    records = [d.model_dump() for d in documents]
    family = identity.families(records)
    pub_id = {d.amass_id: identity.canonical_id(d.model_dump()) for d in documents}
    by_amass = {d.amass_id: d for d in documents}
    cross = {d.amass_id for d in documents if identity.strong_keys(d.model_dump()) & indra_keys}
    additional = [d for d in documents if d.amass_id not in cross]

    support: dict[str, str] = {}
    oppose: dict[str, str] = {}
    mismatch, mention, retracted, awaiting = set(), set(), set(), 0
    for passage in passages:
        document = by_amass.get(passage.amass_id or "")
        if document is None or document.amass_id in cross:
            continue  # text from a paper INDRA already cites adds nothing new
        pid = pub_id[document.amass_id]
        if document.is_retracted is True:
            retracted.add(pid)
            continue
        stance = qualifying_stance(passage, document, policy, allow_partial_context)
        if stance == "support":
            support[pid] = family[pid]
        elif stance == "oppose":
            oppose[pid] = family[pid]
        elif passage.stance in {"supports", "opposes"} and passage.context_match == "mismatch":
            mismatch.add(pid)
        elif qualifying_stance(passage, document, "allow_labelled_unreviewed", allow_partial_context):
            awaiting += 1
    counted = set(support) | set(oppose) | mismatch | retracted
    for document in additional:
        pid = pub_id[document.amass_id]
        if document.is_retracted is True:
            retracted.add(pid)
        elif pid not in counted:
            mention.add(pid)  # retrieved without a qualifying passage: never support

    if unavailable:
        status = "unavailable"
    elif truncated:
        status = "truncated"
    elif support and oppose:
        status = "mixed_evidence"
    elif oppose:
        status = "opposing_evidence_found"
    elif support:
        status = "additional_support_found"
    elif mismatch:
        status = "context_mismatch"
    elif mention:
        status = "mention_only"
    elif cross:
        status = "cross_indexed_only"
    else:
        status = "no_additional_evidence_found" if searched else "not_requested"

    limitations = [FAMILY_LIMIT] + ([BOUNDED_SEARCH] if searched else [])
    if awaiting:
        limitations.append(f"{awaiting} classified passages would qualify but await review under the current policy.")
    if retracted:
        limitations.append(f"{len(retracted)} retracted publications are shown but never counted as corroboration.")
    if policy == "allow_labelled_unreviewed" and (support or oppose):
        limitations.append("Qualifying passages include unreviewed machine classifications.")

    pipelines = set()
    for value in source_classes:
        if value in {"curated_database", "mixed"}:
            pipelines.add("curated_database")
        if value in {"machine_read", "mixed", "machine_read_literature"}:
            pipelines.add("machine_read_literature")
    if documents:
        pipelines.add("amass_retrieval")

    return ClaimCorroboration(
        claim_id=claim_id, status=status,
        cross_indexed_publication_ids=sorted(pub_id[a] for a in cross),
        additional_supporting_publication_ids=sorted(support),
        opposing_publication_ids=sorted(oppose),
        mention_only_publication_ids=sorted(mention),
        distinct_publication_families=len({family[pub_id[d.amass_id]] for d in additional}),
        distinct_primary_study_count=len(set(support.values()) | set(oppose.values())),
        source_pipeline_classes=sorted(pipelines), documents=documents, passages=passages,
        searched_queries=searched_queries, limitations=limitations, truncated=truncated,
    )