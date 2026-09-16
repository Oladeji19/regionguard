from datetime import UTC, datetime, timedelta

from remediator import app


class FakeTable:
    def __init__(self):
        self.calls = []

    def update_item(self, **kwargs):
        self.calls.append(kwargs)
        return {"Attributes": {"incident_status": "RESOLVED"}}


class FakeCloudWatch:
    def __init__(self):
        self.calls = []

    def put_metric_data(self, **kwargs):
        self.calls.append(kwargs)


def test_successful_remediation_updates_incident(monkeypatch):
    table = FakeTable()
    cloudwatch = FakeCloudWatch()
    monkeypatch.setattr(app, "_table", table)
    monkeypatch.setattr(app, "_cloudwatch_client", cloudwatch)

    result = app.handler(
        {
            "event_id": "event-1",
            "service_id": "payments-api",
            "service_key": "us-east-1#payments-api",
            "region": "us-east-1",
            "observed_at": (datetime.now(UTC) - timedelta(seconds=2)).isoformat(),
            "simulate_recovery_success": True,
        },
        None,
    )

    assert result["recovery_success"] is True
    assert result["incident_status"] == "RESOLVED"
    assert result["recovery_time_ms"] >= 1900
    assert table.calls
    assert cloudwatch.calls

