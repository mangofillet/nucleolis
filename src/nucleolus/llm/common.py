import copy


class ProviderError(Exception):
    def __init__(self, stage: str, code: str, message: str, status_code: int = 502):
        super().__init__(message)
        self.stage, self.code, self.message, self.status_code = stage, code, message, status_code


def provider_schema(model):
    """Strict generation schema; local Pydantic additionally enforces length/range rules.

    Anthropic's grammar supports a subset of JSON Schema. Strip unsupported
    constraints from the generation schema only, retaining them in local validation.
    """
    schema = copy.deepcopy(model.model_json_schema())
    def visit(node):
        if isinstance(node, dict):
            for key in ("default", "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems"):
                node.pop(key, None)
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)
    visit(schema)
    return schema
