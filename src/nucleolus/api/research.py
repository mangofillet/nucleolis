"""Research questions that do not require a reviewed Boolean model or LLM key."""
import asyncio

from fastapi import APIRouter, Depends

from nucleolus.api.simulation import settings_dependency
from nucleolus.llm.settings import Settings
from nucleolus.schemas.research import ResearchRequest, ResearchResponse
from nucleolus.services.research import analyze, interpret

router = APIRouter(prefix="/api/research", tags=["research"])


def snapshot_dependency():
    from nucleolus.api.main import snapshot
    return snapshot()


@router.get("/capabilities")
def capabilities(snap=Depends(snapshot_dependency), settings: Settings = Depends(settings_dependency)):
    return {
        "snapshot_id": snap.id,
        "entity_count": len(snap.entities),
        "claim_count": len(snap.claims),
        "publication_count": len(snap.documents),
        "entities": [{"id": e["id"], "name": e.get("preferred_name") or e["id"], "kind": e.get("entity_type")} for e in snap.entities.values()],
        "question_types": ["outgoing", "incoming", "connection", "intervention", "target_discovery", "overview"],
        "local_questions_available": True,
        "language_parser_configured": bool(settings.nebius_model and settings.nebius_api_key.get_secret_value()),
        "research_draft_configured": bool(settings.nebius_model and settings.anthropic_model and
                                          settings.anthropic_api_key.get_secret_value() and settings.nebius_api_key.get_secret_value()),
        "species_filters": ["all", "human", "mouse", "rat"],
        "compound_count": sum(e.get("entity_type") in {"chemical", "compound", "drug", "small_molecule"} for e in snap.entities.values()),
        "biological_lanes_available": False,
    }


@router.post("", response_model=ResearchResponse)
async def research_question(request: ResearchRequest, snap=Depends(snapshot_dependency),
                            settings: Settings = Depends(settings_dependency)):
    parsed, parser = await interpret(request.query, snap, settings)
    return await asyncio.to_thread(analyze, request, snap, parsed, parser)
