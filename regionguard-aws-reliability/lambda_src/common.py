"""Shared validation and response helpers for RegionGuard Lambda functions."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

SERVICE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}$")
ALLOWED_STATUSES = {"HEALTHY", "DEGRADED", "UNHEALTHY"}


class ValidationError(ValueError):
    """Raised when an incoming health event is invalid."""


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_json_body(event: dict[str, Any]) -> dict[str, Any]:
    body = event.get("body")
    if body is None:
        raise ValidationError("Request body is required")
    if event.get("isBase64Encoded"):
        raise ValidationError("Base64 request bodies are not supported")
    if isinstance(body, dict):
        return body
    try:
        parsed = json.loads(body)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValidationError("Request body must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValidationError("Request body must be a JSON object")
    return parsed


def normalize_health_event(payload: dict[str, Any]) -> dict[str, Any]:
    service_id = str(payload.get("service_id", "")).strip()
    region = str(payload.get("region", "")).strip()
    status = str(payload.get("status", "")).strip().upper()

    if not SERVICE_ID_PATTERN.fullmatch(service_id):
        raise ValidationError(
            "service_id must be 2-64 characters using letters, numbers, underscores, or hyphens"
        )
    if not re.fullmatch(r"^[a-z]{2}(?:-gov)?-[a-z]+-\d$", region):
        raise ValidationError("region must look like a valid AWS Region")
    if status not in ALLOWED_STATUSES:
        raise ValidationError(f"status must be one of {sorted(ALLOWED_STATUSES)}")

    try:
        latency_ms = int(payload.get("latency_ms", 0))
    except (TypeError, ValueError) as exc:
        raise ValidationError("latency_ms must be an integer") from exc
    if not 0 <= latency_ms <= 300_000:
        raise ValidationError("latency_ms must be between 0 and 300000")

    event_id = str(payload.get("event_id") or uuid.uuid4())
    try:
        uuid.UUID(event_id)
    except ValueError as exc:
        raise ValidationError("event_id must be a UUID when provided") from exc

    observed_at = str(payload.get("observed_at") or utc_now_iso())
    try:
        observed_datetime = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError("observed_at must be an ISO-8601 timestamp") from exc
    if observed_datetime.tzinfo is None:
        raise ValidationError("observed_at must include a timezone")

    simulate_recovery_success = payload.get("simulate_recovery_success", True)
    if not isinstance(simulate_recovery_success, bool):
        raise ValidationError("simulate_recovery_success must be true or false")

    return {
        "event_id": event_id,
        "service_id": service_id,
        "service_key": f"{region}#{service_id}",
        "region": region,
        "status": status,
        "latency_ms": latency_ms,
        "observed_at": observed_at,
        "simulate_recovery_success": simulate_recovery_success,
    }


def api_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
        },
        "body": json.dumps(body),
    }
