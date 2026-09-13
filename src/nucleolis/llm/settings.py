from pathlib import Path

from pydantic import Field, SecretStr

from nucleolis import config
from nucleolis.schemas.simulation import Model


class Settings(Model):
    nebius_api_key: SecretStr = SecretStr("")
    nebius_base_url: str = "https://api.studio.nebius.ai/v1/"
    nebius_model: str = ""
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = "claude-sonnet-4-6"
    # Nebius drafts the cited synthesis; Claude remains available only by explicit opt-in.
    synthesis_provider: str = Field(default="nebius", pattern="^(nebius|anthropic)$")
    nebius_synthesis_model: str = ""
    timeout: float = Field(default=30, gt=0, le=120)
    total_timeout: float = Field(default=65, gt=0, le=180)
    parser_tokens: int = Field(default=1000, ge=100, le=4000)
    synthesis_tokens: int = Field(default=3000, ge=100, le=16000)
    # Claude only. Default effort spent the whole output budget on thinking; medium measured valid output and citations.
    synthesis_effort: str = Field(default="medium", pattern="^(low|medium|high|xhigh|max)$")
    review_path: Path | None = None
    boolean_path: Path | None = None
    demo_enabled: bool = False
    exploratory_enabled: bool = False
    # AMASS corroboration: an enrichment channel, disabled by default, never a source of edges.
    amass_api_key: SecretStr = SecretStr("")
    amass_base_url: str = "https://api.amass.tech/api/v1"
    amass_enabled: bool = False
    amass_mode: str = Field(default="cached", pattern="^(disabled|cached|live)$")
    amass_timeout: float = Field(default=15, gt=0, le=60)
    amass_max_calls: int = Field(default=6, ge=1, le=60)
    amass_max_search_results: int = Field(default=20, ge=1, le=300)
    amass_max_record_fetches: int = Field(default=20, ge=1, le=100)
    amass_max_claims: int = Field(default=5, ge=1, le=20)
    amass_include_fulltext: bool = False
    amass_classifier: str = Field(default="metadata_only", pattern="^(metadata_only|nebius)$")
    # Unreviewed machine classifications cannot count as support under the default policy.
    review_policy: str = Field(default="require_approval", pattern="^(require_approval|allow_labelled_unreviewed)$")
    allow_partial_context: bool = False
    # Displayed paths rank by weakest-step publications; belief ordering stays available behind the flag.
    path_ranking: str = Field(default="support", pattern="^(support|belief)$")

    @property
    def synthesis_model(self) -> str:
        if self.synthesis_provider == "anthropic":
            return self.anthropic_model
        return self.nebius_synthesis_model or self.nebius_model

    @property
    def synthesis_configured(self) -> bool:
        key = self.anthropic_api_key if self.synthesis_provider == "anthropic" else self.nebius_api_key
        return bool(key.get_secret_value() and self.synthesis_model)

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
            synthesis_provider=env.get("LLM_SYNTHESIS_PROVIDER") or "nebius",
            nebius_synthesis_model=env.get("NEBIUS_SYNTHESIS_MODEL", ""),
            timeout=env.get("LLM_TIMEOUT_SECONDS", 30), total_timeout=env.get("LLM_TOTAL_TIMEOUT_SECONDS", 65),
            parser_tokens=env.get("LLM_PARSER_MAX_TOKENS", 1000),
            synthesis_tokens=env.get("LLM_SYNTHESIS_MAX_TOKENS", 3000),
            synthesis_effort=env.get("LLM_SYNTHESIS_EFFORT") or "medium",
            review_path=path("NOD_REVIEW_MANIFEST"), boolean_path=path("NOD_BOOLEAN_MANIFEST"),
            demo_enabled=env.get("NOD_ENABLE_SYNTHETIC_DEMO", "false").lower() == "true",
            exploratory_enabled=env.get("NOD_ENABLE_EXPLORATORY_MODE", "true").lower() == "true",
            amass_api_key=env.get("AMASS_API_KEY", ""),
            amass_base_url=env.get("AMASS_BASE_URL") or "https://api.amass.tech/api/v1",
            amass_enabled=env.get("AMASS_ENABLED", "false").lower() == "true",
            amass_mode=env.get("AMASS_MODE") or "cached",
            amass_timeout=env.get("AMASS_TIMEOUT_SECONDS", 15),
            amass_max_calls=env.get("AMASS_MAX_CALLS_PER_REQUEST", 6),
            amass_max_search_results=env.get("AMASS_MAX_SEARCH_RESULTS", 20),
            amass_max_record_fetches=env.get("AMASS_MAX_RECORD_FETCHES", 20),
            amass_max_claims=env.get("AMASS_MAX_CLAIMS", 5),
            amass_include_fulltext=env.get("AMASS_INCLUDE_FULLTEXT", "false").lower() == "true",
            amass_classifier=env.get("AMASS_CLASSIFIER") or "metadata_only",
            review_policy=env.get("NOD_REVIEW_POLICY") or "require_approval",
            allow_partial_context=env.get("NOD_ALLOW_PARTIAL_CONTEXT", "false").lower() == "true",
            path_ranking=env.get("NOD_PATH_RANKING") or "support",
        )
