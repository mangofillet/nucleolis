from pathlib import Path

from pydantic import Field, SecretStr

from nucleolus import config
from nucleolus.schemas.simulation import Model


class Settings(Model):
    nebius_api_key: SecretStr = SecretStr("")
    nebius_base_url: str = "https://api.studio.nebius.ai/v1/"
    nebius_model: str = ""
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = "claude-sonnet-4-6"
    timeout: float = Field(default=30, gt=0, le=120)
    total_timeout: float = Field(default=65, gt=0, le=180)
    parser_tokens: int = Field(default=1000, ge=100, le=4000)
    synthesis_tokens: int = Field(default=3000, ge=100, le=8000)
    review_path: Path | None = None
    boolean_path: Path | None = None
    demo_enabled: bool = False

    @classmethod
    def from_env(cls):
        env = config.env()
        def path(key):
            value = env.get(key)
            if not value:
                return None
            result = Path(value)
            return result if result.is_absolute() else config.REPO_ROOT / result
        return cls(
            nebius_api_key=env.get("NEBIUS_API_KEY", ""),
            nebius_base_url=env.get("NEBIUS_BASE_URL") or cls.model_fields["nebius_base_url"].default,
            nebius_model=env.get("NEBIUS_MODEL", ""),
            anthropic_api_key=env.get("ANTHROPIC_API_KEY", ""),
            anthropic_model=env.get("ANTHROPIC_MODEL") or "claude-sonnet-4-6",
            timeout=env.get("LLM_TIMEOUT_SECONDS", 30), total_timeout=env.get("LLM_TOTAL_TIMEOUT_SECONDS", 65),
            parser_tokens=env.get("LLM_PARSER_MAX_TOKENS", 1000),
            synthesis_tokens=env.get("LLM_SYNTHESIS_MAX_TOKENS", 3000),
            review_path=path("NOD_REVIEW_MANIFEST"), boolean_path=path("NOD_BOOLEAN_MANIFEST"),
            demo_enabled=env.get("NOD_ENABLE_SYNTHETIC_DEMO", "false").lower() == "true",
        )
