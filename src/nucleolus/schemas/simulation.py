"""Wire contracts and versioned review/rule manifests for intervention analysis."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, BeforeValidator, model_validator


def _integer(value):
    if type(value) is not int:
        raise ValueError("expected an integer, not a boolean or coerced value")
    return value


Sign = Annotated[Literal[-1, 1], BeforeValidator(_integer)]
Bit = Annotated[Literal[0, 1], BeforeValidator(_integer)]
Score = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Text = Annotated[str, Field(min_length=1, max_length=4000)]
Id = Annotated[str, Field(min_length=1, max_length=200)]
Ids = Annotated[list[Id], Field(max_length=500)]
Texts = Annotated[list[Text], Field(max_length=40)]
Method = Literal["signed_path_hypothesis", "illustrative_boolean"]
Category = Literal["supportive_only", "opposing_only", "conflicting", "insufficient_evidence", "not_requested"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class SimulateTargetRequest(Model):
    query: Annotated[str, Field(min_length=1, max_length=2000)]
    snapshot_id: Id | None = None
    context_id: Id | None = None
    method: Method = "signed_path_hypothesis"
    boolean_model_id: Id | None = None
    exclude_publication_ids: Annotated[list[Id], Field(max_length=1)] = Field(default_factory=list)
    demo: bool = False

    @model_validator(mode="after")
    def method_binding(self):
        if self.method != "illustrative_boolean" and self.boolean_model_id is not None:
            raise ValueError("boolean_model_id is only valid for illustrative_boolean")
        return self


class EntityMention(Model):
    mention: Text
    candidate_id: Id | None
    resolution: Literal["matched", "ambiguous", "unresolved"]

    @model_validator(mode="after")
    def matched_id(self):
        if (self.resolution == "matched") != (self.candidate_id is not None):
            raise ValueError("only a matched entity may have a candidate_id")
        return self


class ParsedQuery(Model):
    source_entity: EntityMention | None
    target_entity: EntityMention | None
    query_intent: Literal["intervention", "mechanism", "unsupported"]
    intervention: Literal["knockout", "decrease", "increase", "none", "unspecified"]
    desired_readout_direction: Sign | None
    context_text: Text | None
    clarification_reason: Text | None


class GroundedQuery(Model):
    source_id: Id
    target_id: Id
    intervention_direction: Sign
    source_state_id: Id | None = None
    target_state_id: Id | None = None
    context_id: Id | None = None


class StatementRef(Model):
    statement_hash: Id
    statement_type: Id
    belief: Score | None = None


class EvidenceReview(Model):
    evidence_id: Id
    claim_id: Id
    approved: bool = False
    source_checked: bool = False
    context_compatible: bool = False
    reviewer: Id | None = None
    statement_hashes: Ids = Field(default_factory=list)


class ClaimMapping(Model):
    claim_id: Id
    source_state: Id
    target_state: Id
    assumption: Text


class ReviewManifest(Model):
    version: Id
    snapshot_id: Id
    snapshot_checksum: Id
    context_id: Id
    synthetic: bool = False
    selected_entity_ids: Annotated[list[Id], Field(max_length=40)]
    reviews: Annotated[list[EvidenceReview], Field(max_length=10000)]
    mappings: Annotated[list[ClaimMapping], Field(max_length=500)]
    statements: Annotated[list[StatementRef], Field(max_length=5000)] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique(self):
        for values in (self.selected_entity_ids, [r.evidence_id for r in self.reviews],
                       [m.claim_id for m in self.mappings], [s.statement_hash for s in self.statements]):
            if len(values) != len(set(values)):
                raise ValueError("manifest identifiers must be unique")
        if self.context_id == "ctx_unknown":
            raise ValueError("a review manifest requires an explicit context")
        return self


class Rule(Model):
    id: Id
    target: Id
    operation: Literal["identity", "not", "and", "or", "signed_threshold"]
    regulators: Annotated[list[Id], Field(min_length=1, max_length=10)]
    signs: Annotated[list[Sign], Field(max_length=10)] = Field(default_factory=list)
    threshold: Annotated[int, Field(strict=True, ge=-10, le=10)] = 0
    assumption: Text
    claim_ids: Ids = Field(default_factory=list)

    @model_validator(mode="after")
    def shape(self):
        if len(set(self.regulators)) != len(self.regulators):
            raise ValueError("a regulator appears only once per rule")
        if self.operation in {"identity", "not"} and len(self.regulators) != 1:
            raise ValueError("identity/not require one regulator")
        if self.operation == "signed_threshold" and len(self.signs) != len(self.regulators):
            raise ValueError("one sign per threshold regulator is required")
        if self.operation != "signed_threshold" and self.signs:
            raise ValueError("signs are only used by signed_threshold")
        return self


class BooleanVariable(Model):
    id: Id
    entity_id: Id
    state: Id
    initial: Bit


class BooleanManifest(Model):
    id: Id
    version: Id
    review_version: Id
    snapshot_checksum: Id
    context_id: Id
    reviewer: Id
    synthetic: bool = False
    readout: Id
    variables: Annotated[list[BooleanVariable], Field(min_length=1, max_length=10)]
    rules: Annotated[list[Rule], Field(min_length=1, max_length=10)]
    assumptions: Texts

    @model_validator(mode="after")
    def consistency(self):
        ids = {v.id for v in self.variables}
        if len(ids) != len(self.variables) or len({v.entity_id for v in self.variables}) != len(ids):
            raise ValueError("one uniquely identified state per entity is supported")
        if self.readout not in ids or {r.target for r in self.rules} != ids or len(self.rules) != len(ids):
            raise ValueError("every variable needs one rule and the readout must resolve")
        if len({r.id for r in self.rules}) != len(self.rules):
            raise ValueError("rule IDs must be unique")
        if any(set(r.regulators) - ids for r in self.rules):
            raise ValueError("rule regulator does not resolve")
        return self


class EvidenceAssessment(Model):
    method: Literal["statement_bottleneck_v1"] = "statement_bottleneck_v1"
    unique_statement_count: int = Field(ge=0)
    scored_statement_count: int = Field(ge=0)
    belief_coverage: Score | None
    weakest_belief: Score | None
    distinct_publication_count: int = Field(ge=0)
    reviewed_evidence_count: int = Field(ge=0)
    limitations: Texts


class NarrativeClaim(Model):
    text: Text
    basis: Literal["evidence", "model_implication", "proposal"]
    claim_ids: Ids
    evidence_ids: Ids
    path_ids: Ids
    rule_ids: Ids

    @model_validator(mode="after")
    def references(self):
        if self.basis == "evidence" and (not self.evidence_ids or not self.claim_ids):
            raise ValueError("evidence claims require claim and evidence references")
        if self.basis == "model_implication" and not (self.path_ids or self.rule_ids):
            raise ValueError("model implications require path or rule references")
        return self


class ValidationProtocol(Model):
    status: Literal["proposed_requires_review"]
    experimental_system: Text | None
    hypothesis: Text
    competing_explanations: Texts
    perturbation: Text
    controls: Texts
    readouts: Texts
    procedure_outline: Texts
    discriminating_observations: Texts
    confounders: Texts
    parameters_to_optimize: Texts


class ClaudeSynthesis(Model):
    biological_rationale: Annotated[list[NarrativeClaim], Field(max_length=20)]
    confidence_assessment: Text
    assumptions: Texts
    limitations: Texts
    validation_protocol: ValidationProtocol | None


class EvidenceItem(Model):
    id: Id
    claim_id: Id
    statement_hashes: Ids
    publication_id: Id | None
    publication_url: str | None
    quote: str | None
    context_id: Id
    review_status: Literal["approved"] = "approved"
    source_api: str | None


class NodeMeta(Model):
    identifier: Id
    description: str | None = None
    taxon: int | None = None


class SimulationNode(Model):
    id: Id
    name: str
    kind: str
    focus: bool
    degree: int = Field(ge=0)
    group: str
    state: Literal["increased", "decreased", "conflicting", "unknown", "on", "off", "unchanged", "not_modeled"]
    state_kind: Literal["directional", "boolean"]
    modeled_state_id: Id | None = None
    baseline_state: Bit | None = None
    perturbed_state: Bit | None = None
    meta: NodeMeta

    @model_validator(mode="after")
    def state_semantics(self):
        if self.state_kind == "directional" and (self.baseline_state is not None or self.perturbed_state is not None):
            raise ValueError("directional inference does not produce Boolean baseline states")
        if (self.baseline_state is None) != (self.perturbed_state is None):
            raise ValueError("Boolean comparison requires both terminal states")
        return self


class SimulationLink(Model):
    id: Id
    source: Id
    target: Id
    predicate: str
    sign: Sign
    papers: int = Field(ge=0)
    sentences: int | None = Field(default=None, ge=0)
    primary: int | None = Field(default=None, ge=0)
    retracted: int = 0
    soleSupportRetracted: bool = False
    belief: Score | None = None
    belief_score: Score | None = None
    belief_method: Literal["minimum_statement_belief", "unavailable"] = "unavailable"
    statement_refs: list[StatementRef]
    evidence_ids: Ids
    publication_ids: Ids
    eligible: bool = True
    exclusion_reason: str | None = None

    @model_validator(mode="after")
    def aliases(self):
        if self.belief != self.belief_score:
            raise ValueError("belief aliases must match")
        return self


class SignedPath(Model):
    id: Id
    node_ids: Ids
    claim_ids: Ids
    evidence_ids: Ids
    implied_direction: Sign
    belief_score: Score | None


class DirectionResult(Model):
    node_id: Id
    possible_directions: list[Sign]


class PathAnalysis(Model):
    category: Category
    completion: Literal["complete_within_limits", "truncated", "error"]
    paths: list[SignedPath]
    directions: list[DirectionResult]
    examined_candidates: int = Field(ge=0)
    total_paths: int = Field(ge=0)
    display_paths_omitted: int = Field(ge=0)


class StateVector(Model):
    step: int = Field(ge=0)
    values: dict[Id, Bit]


class BooleanRun(Model):
    completion: Literal["fixed_point", "cycle", "max_steps"]
    trajectory: list[StateVector]
    terminal: dict[Id, Bit] | None


class StateFlip(Model):
    variable_id: Id
    entity_id: Id
    before: Bit
    after: Bit


class BooleanAnalysis(Model):
    baseline: BooleanRun
    perturbed: BooleanRun
    flips: list[StateFlip]
    rules: list[Rule]
    assumptions: Texts


class AnalysisResult(Model):
    baseline: PathAnalysis
    after_exclusion: PathAnalysis | None = None
    exclusion_effect: Literal["not_requested", "no_change", "support_reduced", "sole_support_lost", "conflict_resolved", "indeterminate"] = "not_requested"
    boolean: BooleanAnalysis | None = None


class SnapshotIdentity(Model):
    id: str
    schema_version: int
    checksum: str | None


class Limits(Model):
    max_nodes: int = Field(default=40, ge=1, le=40)
    max_edges: int = Field(default=500, ge=1, le=500)
    max_hops: int = Field(default=2, ge=1, le=2)
    candidate_budget: int = Field(default=5000, ge=1, le=5000)
    display_paths: int = Field(default=5, ge=2, le=5)
    graph_seconds: float = Field(default=1.0, gt=0, le=1)
    boolean_steps: int = Field(default=20, ge=1, le=20)


class Truncation(Model):
    nodes: bool = False
    edges: bool = False
    search: bool = False
    evidence_bundle: bool = False
    display_paths_omitted: int = 0


class PipelineError(Model):
    stage: Literal["request", "parser", "analysis", "synthesis"]
    code: str
    message: str


class PipelineProvenance(Model):
    parser_model: str | None = None
    synthesis_model: str | None = None
    prompt_version: str = "sandwich_v1"


class SimulateTargetResponse(Model):
    schema_version: Literal[1] = 1
    request_id: str
    status: Literal["completed", "needs_clarification", "model_not_ready", "partial"]
    snapshot: SnapshotIdentity
    analysis_version: str = "qualitative_v1"
    review_manifest_version: str | None = None
    rule_model_version: str | None = None
    method: Method
    synthetic: bool = False
    parsed_query: ParsedQuery | None = None
    grounded_query: GroundedQuery | None = None
    analysis: AnalysisResult | None = None
    evidence_assessment: EvidenceAssessment | None = None
    synthesis: ClaudeSynthesis | None = None
    synthesis_status: Literal["generated", "unavailable", "invalid", "not_requested"] = "not_requested"
    nodes: list[SimulationNode] = Field(default_factory=list)
    links: list[SimulationLink] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    limits: Limits = Field(default_factory=Limits)
    truncation: Truncation = Field(default_factory=Truncation)
    warnings: list[str] = Field(default_factory=list)
    errors: list[PipelineError] = Field(default_factory=list)
    provenance: PipelineProvenance = Field(default_factory=PipelineProvenance)

    @model_validator(mode="after")
    def graph_integrity(self):
        nodes = {n.id for n in self.nodes}
        links = {e.id: e for e in self.links}
        evidence = {e.id for e in self.evidence}
        if len(nodes) != len(self.nodes) or len(links) != len(self.links) or len(evidence) != len(self.evidence):
            raise ValueError("graph identifiers must be unique")
        if any(e.source not in nodes or e.target not in nodes or set(e.evidence_ids) - evidence for e in self.links):
            raise ValueError("graph references must resolve")
        if self.analysis:
            for result in [self.analysis.baseline, self.analysis.after_exclusion]:
                if result and any(set(p.node_ids) - nodes or set(p.claim_ids) - links.keys() or
                                  set(p.evidence_ids) - evidence for p in result.paths):
                    raise ValueError("path references must resolve")
        if (self.synthesis_status == "generated") != (self.synthesis is not None):
            raise ValueError("synthesis status does not match its payload")
        if self.status in {"needs_clarification", "model_not_ready"} and (self.analysis is not None or self.synthesis is not None):
            raise ValueError("unexecuted results cannot contain analysis or synthesis")
        if self.analysis is not None and (self.method == "illustrative_boolean") != (self.analysis.boolean is not None):
            raise ValueError("analysis payload must match the method actually executed")
        return self
