"""Additive intervention endpoint; existing snapshot browsing stays independent."""
from fastapi import APIRouter, Depends, HTTPException

from nucleolis.analysis import adapter, bel_adapter, demo
from nucleolis.graph import queries
from nucleolis.llm.common import ProviderError
from nucleolis.llm.nebius import NebiusParser
from nucleolis.llm.scientist import build_scientist
from nucleolis.llm.settings import Settings
from nucleolis.schemas.simulation import BooleanManifest, PipelineError, SimulateTargetRequest, SimulateTargetResponse
from nucleolis.services.simulate_target import SimulationService

router = APIRouter(prefix="/api", tags=["intervention"])


def settings_dependency():
    return Settings.from_env()


def service_dependency(settings: Settings = Depends(settings_dependency)):
    return SimulationService(settings, NebiusParser(settings), build_scientist(settings))


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
        "synthesis_configured": settings.synthesis_configured,
        "parser_model": settings.nebius_model or None,
        "synthesis_provider": settings.synthesis_provider,
        "synthesis_model": settings.synthesis_model or None,
        "review_manifest_version": review.version if review else None,
        "context_id": review.context_id if review else None,
        "review_issue": issue,
        "boolean_manifest_configured": settings.boolean_path is not None,
        "pybel_available": bel_adapter.available(),
        "synthetic_demo_enabled": settings.demo_enabled,
        "exploratory_mode_enabled": settings.exploratory_enabled and review is None,
        # Configured means a key is present, never that a live call succeeded. No key or balance here.
        "amass_configured": bool(settings.amass_api_key.get_secret_value()),
        "amass_enabled": settings.amass_enabled,
        "amass_allowed_modes": (["disabled"] if not settings.amass_enabled
                                else ["disabled", "cached", "live"] if settings.amass_mode == "live"
                                else ["disabled", "cached"]),
        "amass_max_claims": settings.amass_max_claims,
        "amass_max_search_results": settings.amass_max_search_results,
        "amass_include_fulltext": settings.amass_include_fulltext,
        "review_policy": settings.review_policy,
        "path_ranking": settings.path_ranking,
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
