from __future__ import annotations

import json
import os
from typing import Any

import boto3
from common import ValidationError, api_response, normalize_health_event, parse_json_body

_sqs_client = None


def get_sqs_client():
    global _sqs_client
    if _sqs_client is None:
        _sqs_client = boto3.client("sqs")
    return _sqs_client


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    try:
        health_event = normalize_health_event(parse_json_body(event))
    except ValidationError as exc:
        return api_response(400, {"error": str(exc)})

    get_sqs_client().send_message(
        QueueUrl=os.environ["QUEUE_URL"],
        MessageBody=json.dumps(health_event, separators=(",", ":")),
    )

    return api_response(
        202,
        {
            "event_id": health_event["event_id"],
            "message": "Health event accepted",
        },
    )

