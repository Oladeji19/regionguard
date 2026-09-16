import json
from decimal import Decimal

from status import app


class FakeTable:
    def __init__(self):
        self.scan_calls = []
        self.query_calls = []

    def scan(self, **kwargs):
        self.scan_calls.append(kwargs)
        return {
            "Items": [
                {
                    "event_id": "event-1",
                    "observed_at": "2026-01-01T00:00:00+00:00",
                    "recovery_time_ms": Decimal("500"),
                }
            ]
        }

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        return {"Items": []}


def test_lists_recent_incidents(monkeypatch):
    table = FakeTable()
    monkeypatch.setattr(app, "_table", table)

    response = app.handler({"queryStringParameters": {"limit": "10"}}, None)
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert body["incidents"][0]["recovery_time_ms"] == 500
    assert table.scan_calls == [{"Limit": 10}]


def test_requires_service_and_region_together(monkeypatch):
    monkeypatch.setattr(app, "_table", FakeTable())
    response = app.handler(
        {"queryStringParameters": {"service_id": "payments-api"}},
        None,
    )
    assert response["statusCode"] == 400

