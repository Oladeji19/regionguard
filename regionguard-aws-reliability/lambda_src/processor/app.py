from __future__ import annotations

import json
import os
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError
from common import normalize_health_event

_table = None
_cloudwatch_client = None
_stepfunctions_client = None


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


def get_stepfunctions_client():
    global _stepfunctions_client
    if _stepfunctions_client is None:
        _stepfunctions_client = boto3.client("stepfunctions")
    return _stepfunctions_client


def publish_health_metrics(health_event: dict[str, Any]) -> None:
    metric_name = {
        "HEALTHY": "HealthyEvents",
        "DEGRADED": "DegradedEvents",
        "UNHEALTHY": "UnhealthyEvents",
    }[health_event["status"]]
    get_cloudwatch_client().put_metric_data(
        Namespace=os.getenv("METRIC_NAMESPACE", "RegionGuard"),
        MetricData=[
            {
                "MetricName": metric_name,
                "Value": 1,
                "Unit": "Count",
            },
            {
                "MetricName": metric_name,
                "Dimensions": [
                    {"Name": "ServiceId", "Value": health_event["service_id"]},
                    {"Name": "Region", "Value": health_event["region"]},
                ],
                "Value": 1,
                "Unit": "Count",
            },
            {
                "MetricName": "LatencyMs",
                "Dimensions": [
                    {"Name": "ServiceId", "Value": health_event["service_id"]}
                ],
                "Value": health_event["latency_ms"],
                "Unit": "Milliseconds",
            },
        ],
    )


def persist_once(health_event: dict[str, Any]) -> bool:
    item = {
        **health_event,
        "incident_status": "OPEN" if health_event["status"] == "UNHEALTHY" else "NONE",
        "expires_at": int(time.time()) + (30 * 24 * 60 * 60),
    }
    try:
        get_table().put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(event_id)",
        )
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def process_record(record: dict[str, Any]) -> None:
    health_event = normalize_health_event(json.loads(record["body"]))
    is_new_event = persist_once(health_event)
    if not is_new_event:
        print(
            json.dumps(
                {
                    "message": "duplicate_event_skipped",
                    "event_id": health_event["event_id"],
                }
            )
        )
    else:
        publish_health_metrics(health_event)

    if health_event["status"] == "UNHEALTHY":
        try:
            get_stepfunctions_client().start_execution(
                stateMachineArn=os.environ["STATE_MACHINE_ARN"],
                name=f"incident-{health_event['event_id']}",
                input=json.dumps(health_event, separators=(",", ":")),
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ExecutionAlreadyExists":
                raise


def handler(event: dict[str, Any], _context: Any) -> dict[str, list[dict[str, str]]]:
    failures = []
    for record in event.get("Records", []):
        try:
            process_record(record)
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "message": "record_processing_failed",
                        "message_id": record.get("messageId"),
                        "error": str(exc),
                    }
                )
            )
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
