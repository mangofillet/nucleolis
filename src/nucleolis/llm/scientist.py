"""Chooses the provider that drafts the cited synthesis: Nebius unless LLM_SYNTHESIS_PROVIDER=anthropic."""
from nucleolis.llm.claude import ClaudeScientist
from nucleolis.llm.nebius import NebiusScientist
from nucleolis.llm.settings import Settings


def build_scientist(settings: Settings):
    return ClaudeScientist(settings) if settings.synthesis_provider == "anthropic" else NebiusScientist(settings)
