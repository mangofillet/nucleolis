"""Citation validation for corroboration records.

An identifier the bundle does not contain cites nothing, so it is removed and
disclosed rather than destroying an otherwise valid draft. Misusing a record that
IS in the bundle - wrong claim, or a mention-only passage sold as evidence - stays
a hard rejection.
"""
from __future__ import annotations

import pytest

from nucleolis.schemas.simulation import ClaudeSynthesis, NarrativeClaim
from nucleolis.services.simulate_target import validate_citations

CLAIM = "clm_1"


def passage(stance: str = "supports", claim_id: str = CLAIM) -> dict:
    return {"id": "amp_1", "publication_id": "pmid:222", "claim_id": claim_id, "quote": "Fixture quote.",
            "stance": stance, "review_status": "unreviewed"}


def bundle(passages=()) -> dict:
    return {
        "links": [{"id": CLAIM, "evidence_ids": ["evd_1"]}],
        "evidence": [{"id": "evd_1", "claim_id": CLAIM}],
        "analysis": {"baseline": {"paths": []}, "after_exclusion": None},
        "amass_corroboration": {"corroborations": [
            {"claim_id": CLAIM, "documents": [{"amass_id": "AMBC_1"}], "passages": list(passages)}]},
    }


def synthesis(**kwargs) -> ClaudeSynthesis:
    item = NarrativeClaim(text="Fixture narrative.", basis=kwargs.pop("basis", "evidence"), claim_ids=[CLAIM],
                          evidence_ids=["evd_1"], path_ids=kwargs.pop("path_ids", []),
                          rule_ids=kwargs.pop("rule_ids", []), **kwargs)
    return ClaudeSynthesis(biological_rationale=[item], confidence_assessment="Fixture.",
                           assumptions=[], limitations=[], validation_protocol=None)


def test_unknown_corroboration_ids_are_dropped_and_disclosed():
    draft = synthesis(amass_document_ids=["AMBC_MISSING"], amass_passage_ids=["amp_missing"])
    notes = validate_citations(draft, bundle())
    assert draft.biological_rationale[0].amass_document_ids == []
    assert draft.biological_rationale[0].amass_passage_ids == []
    assert notes and "2 corroboration identifiers" in notes[0]


def test_known_ids_are_kept_without_a_note():
    draft = synthesis(amass_document_ids=["AMBC_1"], amass_passage_ids=["amp_1"])
    notes = validate_citations(draft, bundle([passage()]))
    assert draft.biological_rationale[0].amass_passage_ids == ["amp_1"]
    assert notes == []


def test_passage_from_another_claim_is_rejected():
    draft = synthesis(amass_passage_ids=["amp_1"])
    with pytest.raises(ValueError, match="another claim"):
        validate_citations(draft, bundle([passage(claim_id="clm_other")]))


@pytest.mark.parametrize("stance", ["mention_only", "unclear"])
def test_non_relational_passage_cannot_support_an_evidence_claim(stance):
    draft = synthesis(amass_passage_ids=["amp_1"])
    with pytest.raises(ValueError, match="non-relational"):
        validate_citations(draft, bundle([passage(stance=stance)]))


def test_model_implication_may_cite_a_mention_only_passage():
    draft = synthesis(basis="model_implication", path_ids=["path_1"], amass_passage_ids=["amp_1"])
    data = bundle([passage(stance="mention_only")])
    data["analysis"]["baseline"]["paths"] = [{"id": "path_1", "claim_ids": [CLAIM]}]
    assert validate_citations(draft, data) == []
    draft.biological_rationale[0].path_ids = []
    with pytest.raises(ValueError):
        # A model implication still needs a path or rule reference; the schema enforces that.
        ClaudeSynthesis.model_validate(draft.model_dump())
