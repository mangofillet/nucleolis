import json

from anthropic import AsyncAnthropic, APIError, APITimeoutError
from pydantic import ValidationError

from nucleolus.llm.common import ProviderError, provider_schema
from nucleolus.llm.prompts import CLAUDE_SYSTEM
from nucleolus.llm.settings import Settings
from nucleolus.schemas.simulation import ClaudeSynthesis


class ClaudeScientist:
    def __init__(self, settings: Settings, client=None):
        self.settings, self.client = settings, client
        self.model = settings.anthropic_model

    async def synthesize(self, bundle: dict) -> ClaudeSynthesis:
        if self.client is None and not self.settings.anthropic_api_key.get_secret_value():
            raise ProviderError("synthesis", "not_configured", "Set ANTHROPIC_API_KEY to generate the research draft.", 503)
        client = self.client or AsyncAnthropic(api_key=self.settings.anthropic_api_key.get_secret_value(),
                                             timeout=self.settings.timeout, max_retries=0)
        try:
            schema = provider_schema(ClaudeSynthesis)
            response = await client.messages.create(
                model=self.model, max_tokens=self.settings.synthesis_tokens,
                system=CLAUDE_SYSTEM,
                output_config={"effort": self.settings.synthesis_effort,
                               "format": {"type": "json_schema", "schema": schema}},
                messages=[{"role": "user", "content": json.dumps({"evidence_bundle": bundle, "output_schema": schema})}],
            )
            if response.stop_reason != "end_turn":
                raise ProviderError("synthesis", "incomplete_output", "Claude refused or did not complete its structured response.")
            content = "".join(block.text for block in response.content if block.type == "text")
            try:
                return ClaudeSynthesis.model_validate_json(content)
            except ValidationError as exc:
                raise ProviderError("synthesis", "invalid_output", "Claude output failed schema validation.") from exc
        except APITimeoutError as exc:
            raise ProviderError("synthesis", "timeout", "Claude request timed out.", 504) from exc
        except APIError as exc:
            raise ProviderError("synthesis", "upstream_error", "Claude could not complete synthesis; check model and credentials.") from exc
        finally:
            if self.client is None:
                await client.close()
