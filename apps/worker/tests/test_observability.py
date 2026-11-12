import json
import logging

from store_operator_worker.observability import JsonRedactingFormatter


def test_worker_json_logs_include_job_correlation_and_redact_nested_secrets() -> None:
    record = logging.LogRecord(
        name="store_operator.worker",
        level=logging.ERROR,
        pathname=__file__,
        lineno=12,
        msg="job.execution.unexpected",
        args=(),
        exc_info=None,
    )
    record.job_id = "job-123"
    record.attempt_id = "attempt-2"
    record.authorization = "Bearer never-log-this"
    record.context = {
        "refresh_token": "refresh-never-log-this",
        "safe_label": "image-quality",
        "nested": [{"api-key": "key-never-log-this"}],
    }

    payload = json.loads(JsonRedactingFormatter().format(record))

    assert payload["event"] == "job.execution.unexpected"
    assert payload["service"] == "store-operator-worker"
    assert payload["correlation_id"] == "job-123"
    assert payload["job_id"] == "job-123"
    assert payload["authorization"] == "[REDACTED]"
    assert payload["context"]["refresh_token"] == "[REDACTED]"
    assert payload["context"]["nested"][0]["api-key"] == "[REDACTED]"
    assert payload["context"]["safe_label"] == "image-quality"
    assert "never-log-this" not in json.dumps(payload)
