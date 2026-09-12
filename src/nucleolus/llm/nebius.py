import json

from openai import AsyncOpenAI, APIError, APITimeoutError
from pydantic import ValidationError

from nucleolus.llm.common import ProviderError, provider_schema
from nucleolus.llm.prompts import NEBIUS_SYSTEM
from nucleolus.llm.settings import Settings
from nucleolus.schemas.simulation import ParsedQuery


class NebiusParser:
    def __init__(self, settings: Settings, client=None):
        self.settings, self.client = settings, client
        self.model = settings.nebius_model

    async def parse(self, question: str, entity_catalog: list[dict]) -> ParsedQuery:
        if not self.model or (self.client is None and not self.settings.nebius_api_key.get_secret_value()):
            raise ProviderError("parser", "not_configured", "Set NEBIUS_API_KEY and NEBIUS_MODEL for live query parsing.", 503)
        owned = self.client is None
        client = self.client or AsyncOpenAI(api_key=self.settings.nebius_api_key.get_secret_value(),
                                          base_url=self.settings.nebius_base_url, timeout=self.settings.timeout,
                                          max_retries=0)
        schema = provider_schema(ParsedQuery)
        messages = [{"role": "system", "content": NEBIUS_SYSTEM}, {"role": "user", "content": json.dumps({
            "question": question, "entity_catalog": {"complete": True, "entities": entity_catalog},
            "output_schema": schema,
        })}]
        try:
            for attempt in range(2):
                response = await client.chat.completions.create(
                    model=self.model, temperature=0, max_tokens=self.settings.parser_tokens,
                    response_format={"type": "json_schema", "json_schema": {
                        "name": "parsed_query", "strict": True, "schema": schema}}, messages=messages,
                )
                if not response.choices or response.choices[0].finish_reason != "stop":
                    raise ProviderError("parser", "incomplete_output", "Nebius did not return a complete response.")
                message = response.choices[0].message
                if message.refusal or not message.content:
                    raise ProviderError("parser", "refusal", "Nebius refused or returned empty content.")
                try:
                    parsed = ParsedQuery.model_validate_json(message.content)
                    allowed = {e["id"] for e in entity_catalog}
                    if any(m and m.candidate_id and m.candidate_id not in allowed
                           for m in (parsed.source_entity, parsed.target_entity)):
                        raise ValueError("identifier outside catalog")
                    return parsed
                except (ValidationError, ValueError):
                    if attempt:
                        raise ProviderError("parser", "invalid_output", "Nebius output failed schema or catalog validation.")
                    messages.append({"role": "user", "content": "The response failed schema or catalog validation. Return a corrected JSON object using only the original catalog."})
        except APITimeoutError as exc:
            raise ProviderError("parser", "timeout", "Nebius request timed out.", 504) from exc
        except APIError as exc:
            raise ProviderError("parser", "upstream_error", "Nebius rejected or could not complete the request; check endpoint, model and credentials.") from exc
        finally:
            if owned:
                await client.close()
