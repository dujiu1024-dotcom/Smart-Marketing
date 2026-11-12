from __future__ import annotations

import json
import re
from typing import Any

from store_operator.ai_gateway.errors import ProviderError, ProviderErrorCode
from store_operator.models.prompt_management import PromptVersion

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


class PromptContractError(ValueError):
    """Prompt variables or model output do not satisfy a published prompt contract."""


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def validate_json_schema(value: Any, schema: dict[str, Any], *, path: str = "$") -> None:
    """Validate the deterministic JSON Schema subset used by PromptVersion.

    Supported keywords: type, properties, required, additionalProperties, enum,
    minLength, maxLength, minimum, maximum, items, minItems and maxItems.
    Unsupported keywords fail closed instead of silently weakening validation.
    """
    supported = {
        "type", "properties", "required", "additionalProperties", "enum",
        "minLength", "maxLength", "minimum", "maximum", "items", "minItems", "maxItems",
        "description", "title",
    }
    unknown = set(schema) - supported
    if unknown:
        raise PromptContractError(f"Unsupported JSON Schema keywords at {path}")
    expected = schema.get("type")
    if not isinstance(expected, str) or not _matches_type(value, expected):
        raise PromptContractError(f"JSON Schema type mismatch at {path}")
    if "enum" in schema and value not in schema["enum"]:
        raise PromptContractError(f"JSON Schema enum mismatch at {path}")

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise PromptContractError(f"String is shorter than allowed at {path}")
        if len(value) > schema.get("maxLength", 2**31):
            raise PromptContractError(f"String is longer than allowed at {path}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", float("-inf")):
            raise PromptContractError(f"Number is below minimum at {path}")
        if value > schema.get("maximum", float("inf")):
            raise PromptContractError(f"Number exceeds maximum at {path}")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict) or not isinstance(required, list):
            raise PromptContractError(f"Invalid object schema at {path}")
        missing = [key for key in required if key not in value]
        if missing:
            raise PromptContractError(f"Required property is missing at {path}")
        if schema.get("additionalProperties", True) is False:
            if set(value) - set(properties):
                raise PromptContractError(f"Unexpected object property at {path}")
        for key, child in value.items():
            if key in properties:
                child_schema = properties[key]
                if not isinstance(child_schema, dict):
                    raise PromptContractError(f"Invalid property schema at {path}.{key}")
                validate_json_schema(child, child_schema, path=f"{path}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", 2**31):
            raise PromptContractError(f"Array length is outside allowed bounds at {path}")
        item_schema = schema.get("items")
        if item_schema is not None:
            if not isinstance(item_schema, dict):
                raise PromptContractError(f"Invalid array item schema at {path}")
            for index, child in enumerate(value):
                validate_json_schema(child, item_schema, path=f"{path}[{index}]")


def render_published_prompt(
    version: PromptVersion,
    variables: dict[str, Any],
) -> tuple[str, str]:
    if version.status != "published":
        raise PromptContractError("Only published PromptVersion records can be executed")
    schema = version.variables_schema_json
    validate_json_schema(variables, schema)
    placeholders = set(_PLACEHOLDER.findall(version.user_prompt_template))
    if placeholders != set(schema.get("properties", {})):
        raise PromptContractError("Prompt placeholders do not match the published variable schema")
    rendered = _PLACEHOLDER.sub(lambda match: str(variables[match.group(1)]), version.user_prompt_template)
    return version.system_prompt, rendered


def parse_and_validate_structured_output(
    text: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ProviderError(
            ProviderErrorCode.OUTPUT_INVALID,
            retryable=False,
            user_safe_summary="The generated content was not valid JSON.",
        ) from exc
    try:
        validate_json_schema(value, schema)
    except PromptContractError as exc:
        raise ProviderError(
            ProviderErrorCode.OUTPUT_INVALID,
            retryable=False,
            user_safe_summary="The generated content did not match the published output schema.",
        ) from exc
    if not isinstance(value, dict):
        raise ProviderError(
            ProviderErrorCode.OUTPUT_INVALID,
            retryable=False,
            user_safe_summary="The generated content must be a JSON object.",
        )
    return value
