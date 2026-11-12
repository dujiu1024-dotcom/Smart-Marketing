from types import SimpleNamespace

import pytest

from store_operator_worker.ai_handlers import _prompt_variables
from store_operator_worker.handlers import JobExecutionError


def _generation_context() -> tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace]:
    task = SimpleNamespace(
        title="Weekend promotion",
        task_type="promotion",
        task_options_json={"selected_channel_keys": ["douyin"]},
        strategy_draft_json={},
    )
    requirement = SimpleNamespace(
        payload_json={
            "requirement": {"objective": "Increase store visits"},
            "business_facts": [{"fact_key": "offer", "value": "Buy one get one"}],
        }
    )
    version = SimpleNamespace(
        variables_schema_json={
            "type": "object",
            "properties": {
                "task_title": {"type": "string"},
                "task_type": {"type": "string"},
                "requirement": {"type": "object"},
                "business_facts": {"type": "array"},
                "task_options": {"type": "object"},
                "strategy": {"type": "object"},
                "selected_channels": {"type": "array"},
            },
            "required": ["task_title", "task_type", "requirement", "business_facts"],
        }
    )
    return task, requirement, version


def test_prompt_variables_bind_only_declared_task_context() -> None:
    task, requirement, version = _generation_context()

    variables = _prompt_variables(
        version,
        task=task,
        requirement=requirement,
        strategy=None,
    )

    assert variables == {
        "task_title": "Weekend promotion",
        "task_type": "promotion",
        "requirement": {"objective": "Increase store visits"},
        "business_facts": [{"fact_key": "offer", "value": "Buy one get one"}],
        "task_options": {"selected_channel_keys": ["douyin"]},
        "strategy": {},
        "selected_channels": ["douyin"],
    }


def test_prompt_variables_fail_closed_for_unmapped_schema_properties() -> None:
    task, requirement, version = _generation_context()
    version.variables_schema_json["properties"]["unmapped_business_secret"] = {
        "type": "string"
    }

    with pytest.raises(JobExecutionError) as exc_info:
        _prompt_variables(
            version,
            task=task,
            requirement=requirement,
            strategy=None,
        )

    assert exc_info.value.code == "AI_PROMPT_VARIABLE_UNSUPPORTED"
