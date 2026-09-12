"""Additive intervention endpoint; existing snapshot browsing stays independent."""
from fastapi import APIRouter, Depends, HTTPException

from nucleolus.analysis import adapter, bel_adapter, demo
from nucleolus.graph import queries
from nucleolus.llm.claude import ClaudeScientist
from nucleolus.llm.common import ProviderError
from nucleolus.llm.nebius import NebiusParser
from nucleolus.llm.settings import Settings
from nucleolus.schemas.simulation import BooleanManifest, PipelineError, SimulateTargetRequest, SimulateTargetResponse
from nucleolus.services.simulate_target import SimulationService

router = APIRouter(prefix="/api", tags=["intervention"])


def settings_dependency():
    return Settings.from_env()


def service_dependency(settings: Settings = Depends(settings_dependency)):
    return SimulationService(settings, NebiusParser(settings), ClaudeScientist(settings))


@router.get("/simulation-capabilities")
def capabilities(settings: Settings = Depends(settings_dependency)):
    review = None
    issue = None
    try:
        snap = queries.load_snapshot()
        review = adapter.load_review(settings.review_path, snap)
    except (queries.SnapshotNotFound, adapter.ManifestError) as exc:
        issue = str(exc)
    return {
        "parser_configured": bool(settings.nebius_api_key.get_secret_value() and settings.nebius_model),
        "synthesis_configured": bool(settings.anthropic_api_key.get_secret_value()),
        "parser_model": settings.nebius_model or None,
        "synthesis_model": settings.anthropic_model,
        "review_manifest_version": review.version if review else None,
        "context_id": review.context_id if review else None,
        "review_issue": issue,
        "boolean_manifest_configured": settings.boolean_path is not None,
        "pybel_available": bel_adapter.available(),
        "synthetic_demo_enabled": settings.demo_enabled,
        "demo_query": demo.DEMO_QUERY,
    }


@router.post("/simulate-target", response_model=SimulateTargetResponse)
async def simulate_target(request: SimulateTargetRequest,
                          service: SimulationService = Depends(service_dependency)):
    try:
        if request.demo:
            if not service.settings.demo_enabled:
                raise ProviderError("request", "demo_disabled", "Synthetic demo is disabled; set NOD_ENABLE_SYNTHETIC_DEMO=true to enable it.", 422)
            snap, review, model = demo.fixture()
            service = SimulationService(service.settings, demo.DemoParser(), demo.DemoScientist())
        else:
            snap = queries.load_snapshot()
            review = adapter.load_review(service.settings.review_path, snap)
            if review and review.synthetic:
                raise adapter.ManifestError("Synthetic review manifests require explicit demo mode.")
            model = None
            if service.settings.boolean_path is not None:
                try:
                    model = BooleanManifest.model_validate_json(service.settings.boolean_path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    raise adapter.ManifestError("Boolean rule manifest is missing or invalid.") from exc
        return await service.run(request, snap, review, model)
    except ProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=PipelineError(stage=exc.stage, code=exc.code, message=exc.message).model_dump()) from exc
    except queries.SnapshotNotFound as exc:
        raise HTTPException(status_code=503, detail={"stage": "analysis", "code": "snapshot_unavailable", "message": str(exc)}) from exc
    except adapter.ManifestError as exc:
        raise HTTPException(status_code=409, detail={"stage": "analysis", "code": "invalid_manifest", "message": str(exc)}) from exc
