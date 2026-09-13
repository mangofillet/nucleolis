"""Opt-in live provider check: python -m nucleolis.llm.smoke --live.

Uses fictional evidence so no unreviewed biological findings are presented as
validated. Prints status and model IDs, never credentials or raw provider errors.
"""
import argparse
import asyncio
import json

from nucleolis.analysis import demo
from nucleolis.llm.common import ProviderError
from nucleolis.llm.nebius import NebiusParser
from nucleolis.llm.scientist import build_scientist
from nucleolis.llm.settings import Settings
from nucleolis.schemas.simulation import SimulateTargetRequest
from nucleolis.services.simulate_target import SimulationService


async def run():
    settings = Settings.from_env()
    snap, review, model = demo.fixture()
    service = SimulationService(settings, NebiusParser(settings), build_scientist(settings))
    response = await service.run(SimulateTargetRequest(query=demo.DEMO_QUERY, demo=True, context_id="demo_context"),
                                 snap, review, model)
    print(json.dumps({"status": response.status, "parser_model": service.parser.model,
                      "synthesis_model": service.scientist.model, "synthesis_status": response.synthesis_status,
                      "nodes": len(response.nodes), "links": len(response.links),
                      "errors": [e.model_dump() for e in response.errors], "warnings": response.warnings}))
    if response.status != "completed" or response.synthesis_status != "generated":
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Make up to two parser calls and up to two synthesis calls; consumes provider credits")
    args = parser.parse_args()
    if not args.live:
        parser.error("Explicit --live is required; this check consumes provider credits.")
    try:
        asyncio.run(run())
    except ProviderError as exc:
        print(json.dumps({"stage": exc.stage, "code": exc.code, "message": exc.message}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
