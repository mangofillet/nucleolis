from __future__ import annotations

from nucleolis.graph.queries import Snapshot
from nucleolis.schemas.simulation import GroundedQuery, ParsedQuery


def aliases(entity: dict) -> list[str]:
    values = [entity["id"], entity.get("preferred_name"), entity.get("long_name")]
    if (entity.get("preferred_name") or "").upper() == "TARDBP":
        values += ["TDP-43", "TDP43"]
    return sorted({v for v in values if v})


def catalog(snap: Snapshot) -> list[dict]:
    # This application's frozen graph has 32 entities. Do not silently trim grounding scope.
    if len(snap.entities) > 200:
        raise ValueError("Snapshot exceeds the parser catalog budget of 200 entities.")
    return [{"id": e["id"], "name": e.get("preferred_name"), "aliases": aliases(e)}
            for e in sorted(snap.entities.values(), key=lambda e: e["id"])]


def ground(parsed: ParsedQuery, snap: Snapshot, context_id: str | None) -> tuple[GroundedQuery | None, str | None]:
    # The intervention slot is operative; parsers sometimes label a stated knockout "mechanism".
    if parsed.query_intent == "unsupported" or parsed.intervention not in {"knockout", "decrease", "increase"}:
        return None, "Specify which entity to increase, decrease, or knock out and which readout to inspect."
    resolved = []
    for name, mention in [("source", parsed.source_entity), ("readout", parsed.target_entity)]:
        if mention is None or mention.resolution != "matched":
            return None, f"Specify an unambiguous {name} entity in this snapshot."
        if mention.candidate_id not in snap.entities:
            raise ValueError("Parser returned an entity ID outside the supplied catalog.")
        matches = [e["id"] for e in snap.entities.values()
                   if mention.mention.casefold() in {a.casefold() for a in aliases(e)}]
        if matches != [mention.candidate_id]:
            return None, f"The {name} mention does not uniquely match its proposed catalog entity."
        resolved.append(mention.candidate_id)
    if resolved[0] == resolved[1]:
        return None, "Choose a downstream readout distinct from the intervention target."
    if context_id is not None and (context_id == "ctx_unknown" or context_id not in snap.contexts):
        return None, "Select a known experimental context in the snapshot."
    if parsed.context_text and context_id is None:
        return None, "Bind the stated experimental context to an approved context_id before analysis."
    if parsed.clarification_reason:
        return None, parsed.clarification_reason
    return GroundedQuery(source_id=resolved[0], target_id=resolved[1], context_id=context_id,
                         intervention_direction=1 if parsed.intervention == "increase" else -1), None
