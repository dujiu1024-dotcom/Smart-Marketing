from uuid import uuid4

import pytest

from store_operator.auth.errors import ApiError
from store_operator.models.prompt_management import PromptVersion
from store_operator.prompt_management_router import _validate_prompt_version


def make_version(
    *,
    template: str = "Write a post for {{store_name}}",
    variables: dict[str, object] | None = None,
    output: dict[str, object] | None = None,
) -> PromptVersion:
    return PromptVersion(
        prompt_template_id=uuid4(),
        version_no=1,
        system_prompt="You are a careful store marketing assistant.",
        user_prompt_template=template,
        variables_schema_json=variables
        or {
            "type": "object",
            "properties": {"store_name": {"type": "string"}},
            "required": ["store_name"],
        },
        output_schema_json=output or {"type": "object", "properties": {}},
        schema_version=1,
        input_policy_json={"confirmed_facts_only": True},
        changelog="Initial version",
        status="draft",
    )


def test_prompt_version_accepts_matching_declared_variables() -> None:
    _validate_prompt_version(make_version())


def test_prompt_version_rejects_undeclared_or_unused_variables() -> None:
    version = make_version(
        template="Write for {{store_name}} and {{offer_name}}",
    )
    with pytest.raises(ApiError, match="exactly match"):
        _validate_prompt_version(version)


def test_prompt_version_rejects_required_variable_without_property() -> None:
    version = make_version(
        variables={
            "type": "object",
            "properties": {"store_name": {"type": "string"}},
            "required": ["missing"],
        }
    )
    with pytest.raises(ApiError, match="required variables"):
        _validate_prompt_version(version)


def test_prompt_version_requires_output_schema_type() -> None:
    version = make_version(output={"properties": {}})
    with pytest.raises(ApiError, match="declare a JSON Schema type"):
        _validate_prompt_version(version)
