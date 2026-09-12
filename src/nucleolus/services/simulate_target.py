from __future__ import annotations

import asyncio
import json
import time
import uuid

from nucleolus.analysis import adapter, boolean, confidence, grounding, signed_paths
from nucleolus.graph.queries import Snapshot
from nucleolus.llm.common import ProviderError
from nucleolus.llm.settings import Settings
from nucleolus.schemas.simulation import (
    AnalysisResult, BooleanManifest, NodeMeta, PipelineError, PipelineProvenance,
    SimulateTargetRequest, SimulateTargetResponse, SimulationNode, SnapshotIdentity,
)


def validate_citations(synthesis, bundle):
    claims = {e["id"]: e for e in bundle["links"]}
    evidence = {e["id"]: e for e in bundle["evidence"]}
    paths = {p["id"]: p for result in [bundle["analysis"]["baseline"], bundle["analysis"].get("after_exclusion")]
             if result for p in result["paths"]}
    boolean_result = bundle["analysis"].get("boolean")
    rules = {r["id"]: r for r in boolean_result["rules"]} if boolean_result else {}
    for item in synthesis.biological_rationale:
        if (set(item.claim_ids) - claims.keys() or set(item.evidence_ids) - evidence.keys()
                or set(item.path_ids) - paths.keys() or set(item.rule_ids) - rules.keys()):
            raise ValueError("Synthesis references an identifier outside its evidence bundle.")
        if any(evidence[e]["claim_id"] not in item.claim_ids for e in item.evidence_ids):
            raise ValueError("Synthesis evidence does not belong to its cited claims.")
        if item.path_ids and any(not set(item.claim_ids).issubset(paths[p]["claim_ids"]) for p in item.path_ids):
            raise ValueError("Synthesis claims do not belong to the cited path.")
        if item.rule_ids and set(item.claim_ids) - {c for r in item.rule_ids for c in rules[r]["claim_ids"]}:
            raise ValueError("Synthesis claims do not belong to the cited rules.")


def evidence_bundle(response):
    """Bound input by selecting displayed proof chains, then truncate passages only."""
    bundle = response.model_dump(mode="json", exclude={"synthesis", "nodes", "errors"})
    results = [response.analysis.baseline, response.analysis.after_exclusion]
    claim_ids = {cid for result in results if result for p in result.paths for cid in p.claim_ids}
    if response.analysis.boolean:
        claim_ids |= {cid for rule in response.analysis.boolean.rules for cid in rule.claim_ids}
    bundle["links"] = [e for e in bundle["links"] if e["id"] in claim_ids]
    evidence_ids = {eid for e in bundle["links"] for eid in e["evidence_ids"]}
    selected = [e for e in bundle["evidence"] if e["id"] in evidence_ids]
    omitted = len(bundle["evidence"]) - len(selected)
    # Keep at most 60 citations. If a chain needs more, omit extra evidence from the
    # LLM bundle explicitly, while the full deterministic API payload remains intact.
    omitted += max(0, len(selected) - 60)
    bundle["evidence"] = selected[:60]
    retained = {e["id"] for e in bundle["evidence"]}
    shortened = False
    for item in bundle["evidence"]:
        quote = item["quote"] or ""
        shortened |= len(quote) > 1200
        item["quote"] = quote[:1200]
    for link in bundle["links"]:
        link["evidence_ids"] = [e for e in link["evidence_ids"] if e in retained]
    for result in [bundle["analysis"]["baseline"], bundle["analysis"].get("after_exclusion")]:
        if result:
            for path in result["paths"]:
                path["evidence_ids"] = [e for e in path["evidence_ids"] if e in retained]
    bundle["bundle_coverage"] = {"omitted_evidence_records": omitted, "passages_shortened": shortened,
                                "assessment_scope": "all eligible evidence in the selected graph, not only displayed paths"}
    if len(json.dumps(bundle)) > 140000:
        raise ValueError("Evidence bundle exceeds the synthesis input budget.")
    return bundle, bool(omitted or shortened)


def compute(response, snap, review, model, request):
    query = response.grounded_query
    if review and query.context_id != review.context_id:
        response.status = "needs_clarification"
        response.warnings.append("Select the context_id bound to the review manifest.")
        return response
    if request.exclude_publication_ids and set(request.exclude_publication_ids) - snap.documents.keys():
        raise ProviderError("request", "unknown_publication", "Excluded publication does not exist in this snapshot.", 422)
    baseline_graph = adapter.adapt(snap, review, query.source_id, query.target_id)
    source_states = {baseline_graph.mappings[e.id].source_state for e in baseline_graph.links if e.source == query.source_id}
    target_states = {baseline_graph.mappings[e.id].target_state for e in baseline_graph.links if e.target == query.target_id}
    if len(source_states) > 1 or len(target_states) > 1:
        response.status = "needs_clarification"
        response.warnings.append("The reviewed mechanism has multiple activity/abundance states for a query endpoint; select a manifest with one explicit endpoint state.")
        return response
    query.source_state_id = next(iter(source_states), None)
    query.target_state_id = next(iter(target_states), None)
    baseline = signed_paths.analyze(baseline_graph, query, response.parsed_query.desired_readout_direction)
    effective = baseline_graph
    analysis = AnalysisResult(baseline=baseline)
    if request.exclude_publication_ids:
        effective = adapter.adapt(snap, review, query.source_id, query.target_id, set(request.exclude_publication_ids))
        analysis.after_exclusion = signed_paths.analyze(effective, query, response.parsed_query.desired_readout_direction)
        analysis.exclusion_effect = signed_paths.exclusion_effect(baseline, analysis.after_exclusion)
        if analysis.exclusion_effect == "no_change" and len(effective.evidence) < len(baseline_graph.evidence):
            analysis.exclusion_effect = "support_reduced"
    if request.method == "illustrative_boolean":
        reason = None
        if model is None or review is None:
            reason = "A reviewed Boolean rule manifest is not configured."
        elif request.boolean_model_id != model.id:
            reason = "Select the configured boolean_model_id."
        elif (model.snapshot_checksum != snap.checksum or model.review_version != review.version
              or model.context_id != query.context_id or model.synthetic != response.synthetic):
            reason = "Boolean model does not match the snapshot, review version, or context."
        elif request.exclude_publication_ids:
            reason = "Boolean paper exclusion requires a separately reviewed rule model; use signed-path exclusion."
        elif any(v.entity_id not in baseline_graph.entity_ids for v in model.variables):
            reason = "Boolean variables must belong to the reviewed graph."
        elif next(v.entity_id for v in model.variables if v.id == model.readout) != query.target_id:
            reason = "The requested readout does not match the model's reviewed readout."
        elif {c for r in model.rules for c in r.claim_ids} - {e.id for e in effective.links}:
            reason = "A Boolean rule cites a claim with no surviving eligible evidence."
        elif any(baseline_graph.mappings[e.id].source_state != v.state for v in model.variables
                 for e in effective.links if e.source == v.entity_id) or any(
                 baseline_graph.mappings[e.id].target_state != v.state for v in model.variables
                 for e in effective.links if e.target == v.entity_id):
            reason = "Boolean variable states do not match the reviewed claim state mappings."
        if reason is None:
            try:
                analysis.boolean = boolean.compare(model, query.source_id, response.parsed_query.intervention)
                response.rule_model_version = model.version
            except ValueError as exc:
                reason = str(exc)
        if reason:
            response.status = "model_not_ready"
            response.warnings.append(reason)
            return response
    response.analysis = analysis
    response.evidence_assessment = confidence.assess(effective)
    response.warnings.extend(baseline_graph.warnings)
    response.warnings.extend(w for w in effective.warnings if w not in response.warnings)
    response.truncation.search = any(r and r.completion == "truncated" for r in [baseline, analysis.after_exclusion])
    response.truncation.display_paths_omitted = baseline.display_paths_omitted + (analysis.after_exclusion.display_paths_omitted if analysis.after_exclusion else 0)
    # Baseline graph is retained for exclusion comparison; mark edges that were lost.
    surviving = {e.id for e in effective.links}
    response.links = [e.model_copy(deep=True, update={"eligible": e.id in surviving,
                                                    "exclusion_reason": None if e.id in surviving else "publication_excluded"})
                      for e in baseline_graph.links]
    response.evidence = baseline_graph.evidence
    active_result = analysis.after_exclusion or baseline
    directions = {d.node_id: set(d.possible_directions) for d in active_result.directions}
    for entity_id in baseline_graph.entity_ids:
        entity = snap.entities[entity_id]
        effect = directions.get(entity_id, set())
        state = "conflicting" if len(effect) == 2 else "increased" if effect == {1} else "decreased" if effect == {-1} else "unknown"
        if entity_id == query.source_id:
            state = "increased" if query.intervention_direction == 1 else "decreased"
        before = after = variable_id = None
        if analysis.boolean:
            variable = next((v for v in model.variables if v.entity_id == entity_id), None)
            state = "unknown" if variable else "not_modeled"
            if variable:
                variable_id = variable.id
                if analysis.boolean.baseline.terminal is not None and analysis.boolean.perturbed.terminal is not None:
                    before = analysis.boolean.baseline.terminal[variable.id]
                    after = analysis.boolean.perturbed.terminal[variable.id]
                    state = "unchanged" if before == after else "on" if after else "off"
        kind = entity.get("entity_type") or "entity"
        response.nodes.append(SimulationNode(
            id=entity_id, name=entity.get("preferred_name") or entity_id, kind=kind, group=kind,
            focus=entity_id == query.source_id,
            degree=sum(e.source == entity_id or e.target == entity_id for e in response.links),
            state=state, state_kind="boolean" if analysis.boolean else "directional",
            modeled_state_id=variable_id, baseline_state=before, perturbed_state=after,
            meta=NodeMeta(identifier=entity_id, description=entity.get("long_name"), taxon=entity.get("taxon_id")),
        ))
    return response


class SimulationService:
    def __init__(self, settings: Settings, parser, scientist):
        self.settings, self.parser, self.scientist = settings, parser, scientist

    async def run(self, request: SimulateTargetRequest, snap: Snapshot, review=None, model: BooleanManifest | None = None):
        deadline = time.monotonic() + self.settings.total_timeout
        if request.snapshot_id and request.snapshot_id != snap.id:
            raise ProviderError("request", "stale_snapshot", "Requested snapshot is not the active snapshot.", 409)
        response = SimulateTargetResponse(
            request_id=str(uuid.uuid4()), status="completed", method=request.method, synthetic=request.demo,
            snapshot=SnapshotIdentity(id=snap.id, schema_version=snap.schema_version, checksum=snap.checksum),
            review_manifest_version=review.version if review else None,
            provenance=PipelineProvenance(parser_model=self.parser.model, synthesis_model=self.scientist.model),
        )
        if request.demo:
            response.warnings.append("SYNTHETIC SOFTWARE DEMO: fictional entities, citations, and scores; not biomedical evidence.")
            if self.parser.model == "synthetic_fixture_parser":
                response.warnings.append("Provider responses are explicit software fixtures, not live LLM calls.")
        try:
            async with asyncio.timeout(min(self.settings.timeout, deadline - time.monotonic())):
                response.parsed_query = await self.parser.parse(request.query, grounding.catalog(snap))
            response.grounded_query, reason = grounding.ground(response.parsed_query, snap, request.context_id)
        except TimeoutError as exc:
            raise ProviderError("parser", "timeout", "Query parsing exceeded its deadline.", 504) from exc
        except ValueError as exc:
            raise ProviderError("parser", "invalid_output", "Parser result failed grounding validation.") from exc
        if reason:
            response.status = "needs_clarification"
            response.warnings.append(reason)
            return response
        try:
            response = await asyncio.to_thread(compute, response, snap, review, model, request)
        except adapter.ManifestError as exc:
            raise ProviderError("analysis", "invalid_review", str(exc), 409) from exc
        if response.analysis is None:
            return response
        if not response.links:
            response.warnings.append("Insufficient reviewed evidence; no synthesis or validation protocol was generated.")
            return response
        try:
            bundle, truncated = evidence_bundle(response)
            response.truncation.evidence_bundle = truncated
            async with asyncio.timeout(max(0, min(self.settings.timeout, deadline - time.monotonic()))):
                synthesis = await self.scientist.synthesize(bundle)
            validate_citations(synthesis, bundle)
            response.synthesis = synthesis
            response.synthesis_status = "generated"
        except (ProviderError, TimeoutError, ValueError) as exc:
            response.status = "partial"
            response.synthesis_status = "invalid" if isinstance(exc, ValueError) or getattr(exc, "code", None) == "invalid_output" else "unavailable"
            response.errors.append(PipelineError(stage="synthesis", code=getattr(exc, "code", "timeout" if isinstance(exc, TimeoutError) else "invalid_citations"),
                                                message=exc.message if isinstance(exc, ProviderError) else "Synthesis could not be validated or completed within the request budget."))
        return SimulateTargetResponse.model_validate(response.model_dump())
