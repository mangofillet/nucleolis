"""Wire contracts for the AMASS corroboration and provenance layer.

Deliberately free of imports from `schemas.simulation`: that module imports this
one to carry the summary on its response, so the dependency stays one-way. The
few shared primitives are redeclared rather than shared through a cycle.

Semantics that the types themselves enforce:
  - There is no numeric corroboration score. Categories and counts only.
  - A record that resolves a publication INDRA already cites is cross-indexing,
    never corroboration, so cross-indexed IDs are a separate list.
  - Dates stay verbatim strings. AMASS returns day precision for most records
    and null for some; parsing to `date` would assert precision we did not read.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Id = Annotated[str, Field(min_length=1, max_length=200)]
Ids = Annotated[list[Id], Field(max_length=500)]
Text = Annotated[str, Field(min_length=1, max_length=4000)]
Texts = Annotated[list[Text], Field(max_length=40)]

Mode = Literal["disabled", "cached", "live", "synthetic_fixture"]
Stance = Literal["supports", "opposes", "mention_only", "unclear"]
Resolution = Literal["matched", "ambiguous", "unresolved"]
DirectionMatch = Literal["matched", "opposite", "unspecified"]
ContextMatch = Literal["matched", "partial", "mismatch", "unknown"]
EvidenceRole = Literal["primary_experiment", "secondary_synthesis", "background_citation", "protocol", "unknown"]
ReviewState = Literal["unreviewed", "approved", "rejected"]
SourcePipeline = Literal["curated_database", "machine_read_literature", "amass_retrieval"]

ClaimStatus = Literal[
    "not_requested", "unavailable", "cross_indexed_only", "additional_support_found",
    "opposing_evidence_found", "mixed_evidence", "mention_only", "context_mismatch",
    "no_additional_evidence_found", "truncated",
]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class CorroborationRequest(Model):
    """What the caller asks for. The server clamps every value to its own maxima."""
    mode: Literal["disabled", "cached", "live"] = "cached"
    discover_additional_publications: bool = False
    include_human_evidence: bool = False
    max_claims: Annotated[int, Field(default=5, ge=1, le=20)] = 5


class AmassDocumentMetadata(Model):
    amass_id: Id
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    title: str | None = None
    publication_date: str | None = None   # verbatim; precision is not upgraded
    publication_types: list[str] = Field(default_factory=list, max_length=40)
    journal: str | None = None
    is_retracted: bool | None = None
    has_fulltext: bool | None = None
    citation_count: int | None = Field(default=None, ge=0)
    journal_quality_jufo: int | None = Field(default=None, ge=0, le=3)
    publication_family_id: str | None = None
    retrieval_channel: Literal["amass_biomedcore"] = "amass_biomedcore"


class PassageClassification(Model):
    """Strict output of the bounded classification stage. Never the narrative model's job."""
    claim_id: Id
    publication_id: Id
    quote: Text
    location: str | None = None
    subject_match: Resolution
    object_match: Resolution
    asserted_predicate: str | None = None
    direction_match: DirectionMatch
    negated: bool = False
    epistemic: Literal["observed", "hypothesized", "speculative", "unclear"] = "unclear"
    intervention: str | None = None
    readout: str | None = None
    species: str | None = None
    tissue: str | None = None
    cell_type: str | None = None
    compartment: str | None = None
    assay: str | None = None
    evidence_role: EvidenceRole
    stance: Stance
    context_match: ContextMatch


class CorroboratingPassage(Model):
    id: Id
    publication_id: Id
    amass_id: Id | None = None
    claim_id: Id
    quote: Text
    location: str | None = None
    stance: Stance
    subject_match: Resolution
    object_match: Resolution
    direction_match: DirectionMatch
    context_match: ContextMatch
    evidence_role: EvidenceRole
    classification_method: Text
    review_status: ReviewState = "unreviewed"


class ClaimCorroboration(Model):
    claim_id: Id
    status: ClaimStatus
    cross_indexed_publication_ids: Ids = Field(default_factory=list)
    additional_supporting_publication_ids: Ids = Field(default_factory=list)
    opposing_publication_ids: Ids = Field(default_factory=list)
    mention_only_publication_ids: Ids = Field(default_factory=list)
    # Families, not records: a preprint and its journal article are one study.
    distinct_publication_families: int = Field(default=0, ge=0)
    distinct_primary_study_count: int = Field(default=0, ge=0)
    source_pipeline_classes: list[SourcePipeline] = Field(default_factory=list, max_length=3)
    documents: list[AmassDocumentMetadata] = Field(default_factory=list, max_length=100)
    passages: list[CorroboratingPassage] = Field(default_factory=list, max_length=100)
    searched_queries: Texts = Field(default_factory=list)
    limitations: Texts = Field(default_factory=list)
    truncated: bool = False

    @model_validator(mode="after")
    def qualifying_counts_need_publications(self):
        if self.status == "additional_support_found" and not self.additional_supporting_publication_ids:
            raise ValueError("additional_support_found requires at least one qualifying publication")
        if self.status == "opposing_evidence_found" and not self.opposing_publication_ids:
            raise ValueError("opposing_evidence_found requires at least one opposing publication")
        if self.distinct_primary_study_count > self.distinct_publication_families:
            raise ValueError("primary studies cannot exceed distinct publication families")
        return self


class HumanEvidenceSummary(Model):
    """Trial/drug/regulatory context. Never a 'human validated' badge."""
    status: Literal["not_requested", "unavailable", "completed"] = "not_requested"
    trial_records: Ids = Field(default_factory=list)
    drug_records: Ids = Field(default_factory=list)
    regulatory_records: Ids = Field(default_factory=list)
    limitations: Texts = Field(default_factory=list)


class AmassCorroborationSummary(Model):
    status: Literal["not_requested", "completed", "partial", "unavailable"] = "not_requested"
    mode: Mode = "disabled"
    claims_assessed: int = Field(default=0, ge=0)
    calls_used: int = Field(default=0, ge=0)
    records_examined: int = Field(default=0, ge=0)
    from_cache: bool = False
    retrieved_at: str | None = None
    cache_version: str | None = None
    snapshot_checksum: str | None = None
    review_policy: Literal["require_approval", "allow_labelled_unreviewed"] = "require_approval"
    corroborations: list[ClaimCorroboration] = Field(default_factory=list, max_length=20)
    human_evidence: HumanEvidenceSummary = Field(default_factory=HumanEvidenceSummary)
    truncated: bool = False
    warnings: Texts = Field(default_factory=list)
