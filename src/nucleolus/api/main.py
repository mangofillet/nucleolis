"""Read-only FastAPI service over a frozen snapshot.

EXECUTION_PLAN.md s2: the API never writes the snapshot it serves. s6: every
response identifies the snapshot, the applied filters and any truncation.
Citation inspection must work without an LLM key.
"""
from __future__ import annotations

import pathlib

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from nucleolus import config
from nucleolus.graph import pathways as pathways_mod
from nucleolus.graph import queries
from nucleolus.api.simulation import router as simulation_router
from nucleolus.api.research import router as research_router, research_question
from nucleolus.api.axes import router as axes_router
from nucleolus.schemas.research import ResearchResponse

UI_DIST = config.REPO_ROOT / "ui" / "dist"

app = FastAPI(
    title="Nucleolis",
    version="0.1.0",
    description="Evidence-first literature research tool for brain ageing and cognitive maintenance",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(simulation_router)
app.include_router(research_router)
app.include_router(axes_router)
app.post("/ask", response_model=ResearchResponse, tags=["research"])(research_question)

_snapshot: queries.Snapshot | None = None
_load_error: str | None = None


def snapshot() -> queries.Snapshot:
    global _snapshot, _load_error
    if _snapshot is None:
        try:
            _snapshot = queries.load_snapshot()
            _load_error = None
        except queries.SnapshotNotFound as exc:
            _load_error = str(exc)
            raise HTTPException(status_code=503, detail={"snapshot_unavailable": str(exc)})
    return _snapshot


@app.on_event("startup")
def _warm() -> None:
    global _load_error
    try:
        queries.load_snapshot()
    except queries.SnapshotNotFound as exc:
        _load_error = str(exc)


@app.get("/health")
def health():
    """Service and snapshot readiness. Makes no upstream request."""
    try:
        snap = queries.load_snapshot()
    except queries.SnapshotNotFound as exc:
        return {"status": "degraded", "snapshot_ready": False, "detail": str(exc)}
    return {
        "status": "ok",
        "snapshot_ready": True,
        "snapshot": {
            "id": snap.id,
            "schema_version": snap.schema_version,
            "created_at": snap.created_at,
            "checksum": snap.checksum,
        },
        "coverage": snap.coverage,
        "limitations": snap.limitations,
        "license_note": snap.license_note,
        "capabilities": {
            "evidence_inspection": True,
            "date_filter": False,
            "date_filter_reason": "source provides no publication dates; not inferred",
            "species_marking": True,
            "species_marking_reason": "taxon is present on a minority of evidence "
                                      "records and is shown per quote; evidence "
                                      "without a stated species is labelled as such",
            "context_filter": False,
            "context_filter_reason": "cell type and tissue are too sparse to filter on; "
                                     "species is displayed but not yet filterable",
            "ask": True,
            "ask_reason": "Common research questions run locally; broader wording uses an optional Nebius parser",
        },
    }


@app.get("/nodes/search")
def search_nodes(q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=100)):
    snap = snapshot()
    return {"snapshot_id": snap.id, "query": q, "results": snap.search_nodes(q, limit)}


@app.get("/graph")
def graph(
    node_id: str,
    hops: int = Query(1, ge=1, le=3),
    max_nodes: int = Query(queries.DEFAULT_NODES, ge=1, le=queries.HARD_MAX_NODES),
    causal_only: bool = False,
    min_support: int = Query(0, ge=0),
    edge_scope: str = Query("incident", pattern="^(incident|all)$"),
):
    snap = snapshot()
    try:
        return snap.neighborhood(
            node_id,
            hops=hops,
            max_nodes=max_nodes,
            causal_only=causal_only,
            min_support=min_support,
            edge_scope=edge_scope,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="node not in snapshot: " + node_id)


@app.get("/path")
def path(
    source_id: str,
    target_id: str,
    max_hops: int = Query(queries.MAX_HOPS, ge=1, le=queries.MAX_HOPS),
    max_paths: int = Query(queries.MAX_PATHS, ge=1, le=queries.MAX_PATHS),
    causal_only: bool = True,
):
    snap = snapshot()
    try:
        return snap.paths(
            source_id,
            target_id,
            max_hops=max_hops,
            max_paths=max_paths,
            causal_only=causal_only,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="node not in snapshot: " + str(exc))


@app.get("/pathways")
def pathways(
    source_id: str,
    max_hops: int = Query(queries.MAX_SIGNED_HOPS, ge=1, le=queries.MAX_SIGNED_HOPS),
    max_targets: int = Query(24, ge=1, le=60),
    min_papers: int = Query(1, ge=0),
    target_id: str | None = None,
):
    """Layered routes out of one source: source -> intermediates -> targets.

    One row per target, the best-scoring route only, ranked by the weakest
    supporting leg discounted by intermediate promiscuity.
    """
    snap = snapshot()
    try:
        return pathways_mod.pathways(
            snap,
            source_id,
            max_hops=max_hops,
            max_targets=max_targets,
            min_papers=min_papers,
            target_id=target_id,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="node not in snapshot: " + source_id)


@app.get("/edges/{claim_id}/evidence")
def edge_evidence(
    claim_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
):
    snap = snapshot()
    try:
        return snap.evidence_for_claim(claim_id, offset=offset, limit=limit)
    except KeyError:
        raise HTTPException(status_code=404, detail="claim not in snapshot: " + claim_id)


@app.get("/node/{node_id}/evidence")
def node_evidence(
    node_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
):
    snap = snapshot()
    try:
        return snap.evidence_for_node(node_id, offset=offset, limit=limit)
    except KeyError:
        raise HTTPException(status_code=404, detail="node not in snapshot: " + node_id)


@app.get("/exports/graph")
def export_graph(
    node_id: str,
    hops: int = Query(1, ge=1, le=3),
    max_nodes: int = Query(queries.DEFAULT_NODES, ge=1, le=queries.HARD_MAX_NODES),
):
    """Export selected claims with their evidence and provenance, plus the query
    manifest needed to reproduce the selection."""
    snap = snapshot()
    try:
        view = snap.neighborhood(node_id, hops=hops, max_nodes=max_nodes)
    except KeyError:
        raise HTTPException(status_code=404, detail="node not in snapshot: " + node_id)

    claims = []
    for edge in view["edges"]:
        detail = snap.evidence_for_claim(edge["claim_id"], offset=0, limit=1000)
        claims.append({"claim": detail["claim"], "evidence": detail["evidence"]})

    return {
        "export_version": 1,
        "snapshot": {
            "id": snap.id,
            "schema_version": snap.schema_version,
            "created_at": snap.created_at,
            "checksum": snap.checksum,
        },
        "query_manifest": {
            "node_id": node_id,
            "hops": hops,
            "max_nodes": max_nodes,
            "truncation": view["truncation"],
        },
        "source_query": snap.query,
        "license_note": snap.license_note,
        "limitations": snap.limitations,
        "nodes": view["nodes"],
        "claims": claims,
    }


# ---------------------------------------------------------------------------
# Static UI. Mounted last so it never shadows an API route.
# Absent in a dev checkout that has not run `npm run build`; the API still works.
# ---------------------------------------------------------------------------

if UI_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=UI_DIST / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(UI_DIST / "index.html")

    @app.get("/{asset}", include_in_schema=False)
    def root_asset(asset: str):
        """Serve favicon.svg and friends; anything else falls back to the app."""
        candidate = UI_DIST / asset
        if candidate.is_file() and pathlib.Path(asset).suffix:
            return FileResponse(candidate)
        return FileResponse(UI_DIST / "index.html")
