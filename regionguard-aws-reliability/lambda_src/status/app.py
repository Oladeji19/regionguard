from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from common import api_response

_table = None


def get_table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(os.environ["INCIDENTS_TABLE"])
    return _table


def serialize_value(value: Any):
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    params = event.get("queryStringParameters") or {}
    service_id = params.get("service_id")
    region = params.get("region")
    try:
        limit = min(max(int(params.get("limit", 25)), 1), 100)
    except ValueError:
        return api_response(400, {"error": "limit must be an integer"})

    if bool(service_id) != bool(region):
        return api_response(400, {"error": "service_id and region must be provided together"})

    if service_id and region:
        response = get_table().query(
            IndexName="service-observed-at-index",
            KeyConditionExpression=Key("service_key").eq(f"{region}#{service_id}"),
            ScanIndexForward=False,
            Limit=limit,
        )
    else:
        response = get_table().scan(Limit=limit)

    items = sorted(
        response.get("Items", []),
        key=lambda item: item.get("observed_at", ""),
        reverse=True,
    )
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
        },
        "body": json.dumps(
            {"count": len(items), "incidents": items},
            default=serialize_value,
        ),
    }
