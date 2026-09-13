"""One optional live Nebius research-plan check; does not print credentials.

Run explicitly after configuring .env. Consumes one bounded parser call.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nucleolis.graph.queries import load_snapshot
from nucleolis.llm.settings import Settings
from nucleolis.schemas.research import ResearchRequest
from nucleolis.services.research import analyze, interpret


async def main():
    snap = load_snapshot()
    question = "My hypothesis is that lowering TBK1 would decrease SQSTM1. Can the current evidence support this?"
    parsed, provider = await interpret(question, snap, Settings.from_env())
    result = analyze(ResearchRequest(query=question), snap, parsed, provider)
    print(json.dumps({"parser": provider, "operation": parsed.operation, "source": parsed.source,
                      "target": parsed.target, "perturbation": parsed.perturbation,
                      "desired_direction": parsed.desired_direction, "status": result.status,
                      "path_count": len(result.paths), "answer": result.answer}))
    if provider != "nebius" or result.status != "completed":
        raise SystemExit(1)
    if (parsed.source, parsed.target, parsed.perturbation, parsed.desired_direction) != ("TBK1", "SQSTM1", "decrease", -1):
        raise SystemExit("The live plan did not preserve the requested hypothesis.")


asyncio.run(main())
