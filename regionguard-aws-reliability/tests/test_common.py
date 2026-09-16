import uuid

import pytest
from common import ValidationError, normalize_health_event


def test_normalizes_valid_event():
    result = normalize_health_event(
        {
            "service_id": "payments-api",
            "region": "us-east-1",
            "status": "healthy",
            "latency_ms": "42",
        }
    )

    uuid.UUID(result["event_id"])
    assert result["service_key"] == "us-east-1#payments-api"
    assert result["status"] == "HEALTHY"
    assert result["latency_ms"] == 42
    assert result["simulate_recovery_success"] is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("service_id", "!"),
        ("region", "virginia"),
        ("status", "BROKEN"),
        ("latency_ms", -1),
        ("simulate_recovery_success", "false"),
        ("observed_at", "yesterday"),
    ],
)
def test_rejects_invalid_values(field, value):
    payload = {
        "service_id": "payments-api",
        "region": "us-east-1",
        "status": "HEALTHY",
        "latency_ms": 10,
        field: value,
    }

    with pytest.raises(ValidationError):
        normalize_health_event(payload)

