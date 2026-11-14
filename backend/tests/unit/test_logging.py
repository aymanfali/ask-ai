from ask_ai.core.logging import redact_sensitive_data


def test_redacts_sensitive_fields_recursively() -> None:
    event = {
        "event": "provider_request",
        "authorization": "Bearer top-secret",
        "provider_api_key": "secret-key",
        "providerApiKey": "camel-secret-key",
        "metadata": {"refresh_token": "refresh-secret", "safe": "value"},
        "input_tokens": 10,
    }

    result = redact_sensitive_data(None, "info", event)

    assert result["authorization"] == "[REDACTED]"
    assert result["provider_api_key"] == "[REDACTED]"
    assert result["providerApiKey"] == "[REDACTED]"
    assert result["metadata"]["refresh_token"] == "[REDACTED]"
    assert result["metadata"]["safe"] == "value"
    assert result["input_tokens"] == 10
