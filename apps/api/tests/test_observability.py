from store_operator.observability import redact_sensitive_fields


def test_redact_sensitive_fields_recursively() -> None:
    event = {
        "event": "request.received",
        "authorization": "Bearer top-secret",
        "profile": {
            "password": "pw-value",
            "refresh_token": "refresh-value",
            "nested": [{"api-key": "key-value", "label": "safe"}],
        },
        "safe_value": "visible",
    }

    result = redact_sensitive_fields(None, "info", event)

    assert result["authorization"] == "[REDACTED]"
    assert result["profile"]["password"] == "[REDACTED]"
    assert result["profile"]["refresh_token"] == "[REDACTED]"
    assert result["profile"]["nested"][0]["api-key"] == "[REDACTED]"
    assert result["profile"]["nested"][0]["label"] == "safe"
    assert result["safe_value"] == "visible"
