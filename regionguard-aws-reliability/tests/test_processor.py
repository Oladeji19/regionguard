import json
import uuid

from botocore.exceptions import ClientError
from processor import app


class FakeTable:
    def __init__(self, duplicate=False):
        self.items = []
        self.duplicate = duplicate

    def put_item(self, **kwargs):
        if self.duplicate:
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException", "Message": "duplicate"}},
                "PutItem",
            )
        self.items.append(kwargs["Item"])
        return {}


class FakeCloudWatch:
    def __init__(self):
        self.calls = []

    def put_metric_data(self, **kwargs):
        self.calls.append(kwargs)


class FakeStepFunctions:
    def __init__(self):
        self.executions = []

    def start_execution(self, **kwargs):
        self.executions.append(kwargs)
        return {"executionArn": "arn:execution"}


def record(status="UNHEALTHY"):
    return {
        "messageId": "message-1",
        "body": json.dumps(
            {
                "event_id": str(uuid.uuid4()),
                "service_id": "payments-api",
                "region": "us-east-1",
                "status": status,
                "latency_ms": 500,
                "simulate_recovery_success": True,
            }
        ),
    }


def test_unhealthy_event_starts_remediation(monkeypatch):
    table = FakeTable()
    metrics = FakeCloudWatch()
    workflows = FakeStepFunctions()
    monkeypatch.setattr(app, "_table", table)
    monkeypatch.setattr(app, "_cloudwatch_client", metrics)
    monkeypatch.setattr(app, "_stepfunctions_client", workflows)
    monkeypatch.setenv("STATE_MACHINE_ARN", "arn:aws:states:us-east-1:123:stateMachine:test")

    result = app.handler({"Records": [record()]}, None)

    assert result == {"batchItemFailures": []}
    assert table.items[0]["incident_status"] == "OPEN"
    assert len(workflows.executions) == 1
    assert metrics.calls


def test_duplicate_event_is_idempotently_skipped(monkeypatch):
    workflows = FakeStepFunctions()
    monkeypatch.setattr(app, "_table", FakeTable(duplicate=True))
    monkeypatch.setattr(app, "_cloudwatch_client", FakeCloudWatch())
    monkeypatch.setattr(app, "_stepfunctions_client", workflows)
    monkeypatch.setenv("STATE_MACHINE_ARN", "arn:aws:states:us-east-1:123:stateMachine:test")

    result = app.handler({"Records": [record()]}, None)

    assert result == {"batchItemFailures": []}
    assert len(workflows.executions) == 1


def test_bad_record_reports_partial_batch_failure(monkeypatch):
    monkeypatch.setattr(app, "_table", FakeTable())
    result = app.handler({"Records": [{"messageId": "bad-1", "body": "not-json"}]}, None)
    assert result == {"batchItemFailures": [{"itemIdentifier": "bad-1"}]}
