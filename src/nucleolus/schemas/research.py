"""Question-first exploration contracts, separate from reviewed simulation models."""
from typing import Literal

from pydantic import Field, model_validator

from nucleolus.schemas.simulation import Model, Sign, SnapshotIdentity


class ResearchRequest(Model):
    query: str = Field(min_length=1, max_length=2000)
    species: Literal["all", "human", "mouse", "rat"] = "all"
    max_paths: int = Field(default=8, ge=2, le=12)


class ResearchPlan(Model):
    operation: Literal["outgoing", "incoming", "connection", "intervention", "target_discovery",
                       "overview", "unsupported"]
    source: str | None
    target: str | None
    relation: Literal["activates", "inhibits", "increases_amount", "decreases_amount", "any"]
    perturbation: Literal["increase", "decrease", "knockout", "none"]
    desired_direction: Sign | None
    context: str | None
    reason: str | None


class ResearchNode(Model):
    id: str
    name: str
    description: str | None
    kind: str
    lane: int = Field(ge=0, le=2)
    state: Literal["increased", "decreased", "mixed", "unknown"] = "unknown"
    focus: bool = False


class ResearchLink(Model):
    id: str
    source: str
    target: str
    predicate: str
    sign: Sign
    evidence_ids: list[str]
    publication_ids: list[str]
    source_class: str
    review_status: Literal["reviewed", "unreviewed", "mixed"]
    belief: float | None = None


class ResearchPath(Model):
    id: str
    node_ids: list[str]
    claim_ids: list[str]
    direction: Sign
    intervention: Literal["increase", "decrease", "knockout", "none"] = "none"
    assessment: Literal["supports_direction", "opposes_direction", "directional_hypothesis"]
    assumptions: list[str]


class ResearchResponse(Model):
    schema_version: Literal[1] = 1
    query: str
    status: Literal["completed", "needs_clarification", "insufficient_evidence"]
    snapshot: SnapshotIdentity
    plan: ResearchPlan
    interpretation: str
    answer: str
    parser: Literal["local_grammar", "nebius"] = "local_grammar"
    source_id: str | None = None
    target_id: str | None = None
    species: str
    nodes: list[ResearchNode] = Field(default_factory=list, max_length=24)
    links: list[ResearchLink] = Field(default_factory=list, max_length=48)
    paths: list[ResearchPath] = Field(default_factory=list, max_length=12)
    lanes: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    total_paths: int = 0
    paths_omitted: int = 0
    search_truncated: bool = False
    excluded_evidence_count: int = 0
    basis: Literal["exploratory_literature_graph"] = "exploratory_literature_graph"

    @model_validator(mode="after")
    def references(self):
        nodes = {n.id for n in self.nodes}
        links = {e.id: e for e in self.links}
        if len(nodes) != len(self.nodes) or len(links) != len(self.links):
            raise ValueError("Duplicate graph identifier")
        if any(e.source not in nodes or e.target not in nodes for e in self.links):
            raise ValueError("Unresolved graph endpoint")
        if len({p.id for p in self.paths}) != len(self.paths):
            raise ValueError("Duplicate path identifier")
        for path in self.paths:
            if not 1 <= len(path.claim_ids) <= 2 or len(set(path.node_ids)) != len(path.node_ids):
                raise ValueError("Research paths must be simple and bounded to two steps")
            if set(path.node_ids) - nodes or set(path.claim_ids) - links.keys():
                raise ValueError("Unresolved path reference")
            if len(path.node_ids) != len(path.claim_ids) + 1:
                raise ValueError("Path length mismatch")
            for i, cid in enumerate(path.claim_ids):
                if (links[cid].source, links[cid].target) != tuple(path.node_ids[i:i + 2]):
                    raise ValueError("Path direction mismatch")
        return self
