import json

from ingest import app


class FakeSqs:
    def __init__(self):
        self.messages = []

    def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return {"MessageId": "message-1"}


def test_ingest_accepts_and_queues_event(monkeypatch):
    fake_sqs = FakeSqs()
    monkeypatch.setattr(app, "_sqs_client", fake_sqs)
    monkeypatch.setenv("QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123/health")

    response = app.handler(
        {
            "body": json.dumps(
                {
                    "service_id": "payments-api",
                    "region": "us-east-1",
                    "status": "UNHEALTHY",
                    "latency_ms": 900,
                }
            )
        },
        None,
    )

    assert response["statusCode"] == 202
    queued = json.loads(fake_sqs.messages[0]["MessageBody"])
    assert queued["service_id"] == "payments-api"
    assert queued["status"] == "UNHEALTHY"


def test_ingest_rejects_invalid_json(monkeypatch):
    monkeypatch.setattr(app, "_sqs_client", FakeSqs())
    response = app.handler({"body": "{"}, None)
    assert response["statusCode"] == 400

