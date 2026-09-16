#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from aws_signed_request import signed_request


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a signed health event to RegionGuard")
    parser.add_argument("--api-url", required=True, help="API base URL from the CDK output")
    parser.add_argument("--aws-region", default="us-east-1")
    parser.add_argument("--service-id", default="payments-api")
    parser.add_argument("--service-region", default="us-east-1")
    parser.add_argument(
        "--status",
        choices=["HEALTHY", "DEGRADED", "UNHEALTHY"],
        default="HEALTHY",
    )
    parser.add_argument("--latency-ms", type=int, default=120)
    parser.add_argument("--event-id", help="Optional UUID used to demonstrate idempotency")
    parser.add_argument(
        "--fail-recovery",
        action="store_true",
        help="Make an UNHEALTHY event require manual intervention",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    url = args.api_url.rstrip("/") + "/health"
    payload = {
        "service_id": args.service_id,
        "region": args.service_region,
        "status": args.status,
        "latency_ms": args.latency_ms,
        "simulate_recovery_success": not args.fail_recovery,
    }
    if args.event_id:
        payload["event_id"] = args.event_id

    response = signed_request(
        "POST",
        url,
        args.aws_region,
        payload,
    )
    print(response.status_code)
    print(response.text)
    return 0 if response.ok else 1


if __name__ == "__main__":
    sys.exit(main())
