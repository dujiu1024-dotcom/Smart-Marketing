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



def test_operational_alert_logs_and_posts_only_redacted_attributes(monkeypatch, caplog) -> None:
    from store_operator_worker import observability

    captured: dict[str, object] = {}

    class FakeResponse:
        def close(self) -> None:
            captured["closed"] = True

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setenv("OPS_ALERT_WEBHOOK_URL", "https://alerts.invalid/webhook")
    monkeypatch.setattr(observability, "urlopen", fake_urlopen)

    with caplog.at_level(logging.ERROR, logger="store_operator.worker.alerts"):
        observability.emit_operational_alert(
            event="provider.failure",
            severity="error",
            correlation_id="job-456",
            attributes={"provider": "text-provider", "api_token": "do-not-send"},
        )

    payload = captured["payload"]
    assert captured["url"] == "https://alerts.invalid/webhook"
    assert captured["timeout"] == 3
    assert captured["closed"] is True
    assert payload["event"] == "provider.failure"
    assert payload["correlation_id"] == "job-456"
    assert payload["attributes"]["api_token"] == "[REDACTED]"
    assert "do-not-send" not in json.dumps(payload)
    assert any(record.alert_type == "provider.failure" for record in caplog.records)
