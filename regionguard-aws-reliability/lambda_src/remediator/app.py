from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import boto3

_table = None
_cloudwatch_client = None


def get_table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(os.environ["INCIDENTS_TABLE"])
    return _table


def get_cloudwatch_client():
    global _cloudwatch_client
    if _cloudwatch_client is None:
        _cloudwatch_client = boto3.client("cloudwatch")
    return _cloudwatch_client


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    event_id = event["event_id"]
    recovery_succeeded = event.get("simulate_recovery_success", True)
    resolved_at = datetime.now(UTC)
    observed_at = datetime.fromisoformat(event["observed_at"].replace("Z", "+00:00"))
    recovery_time_ms = max(0, int((resolved_at - observed_at).total_seconds() * 1000))
    incident_status = "RESOLVED" if recovery_succeeded else "MANUAL_INTERVENTION_REQUIRED"

    get_table().update_item(
        Key={"event_id": event_id},
        UpdateExpression=(
            "SET incident_status = :status, resolved_at = :resolved_at, "
            "recovery_time_ms = :recovery_time"
        ),
        ConditionExpression="attribute_exists(event_id)",
        ExpressionAttributeValues={
            ":status": incident_status,
            ":resolved_at": resolved_at.isoformat(),
            ":recovery_time": recovery_time_ms,
        },
        ReturnValues="ALL_NEW",
    )

    get_cloudwatch_client().put_metric_data(
        Namespace=os.getenv("METRIC_NAMESPACE", "RegionGuard"),
        MetricData=[
            {
                "MetricName": "RecoveryTimeMs",
                "Dimensions": [
                    {"Name": "ServiceId", "Value": event["service_id"]},
                    {"Name": "Region", "Value": event["region"]},
                ],
                "Value": recovery_time_ms,
                "Unit": "Milliseconds",
            },
            {
                "MetricName": (
                    "RemediationSuccesses" if recovery_succeeded else "RemediationFailures"
                ),
                "Value": 1,
                "Unit": "Count",
            },
        ],
    )

    return {
        "event_id": event_id,
        "service_id": event["service_id"],
        "region": event["region"],
        "incident_status": incident_status,
        "recovery_success": recovery_succeeded,
        "recovery_time_ms": recovery_time_ms,
    }
