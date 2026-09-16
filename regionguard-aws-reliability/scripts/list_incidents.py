#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from urllib.parse import urlencode

from aws_signed_request import signed_request


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List RegionGuard incidents")
    parser.add_argument("--api-url", required=True, help="API base URL from the CDK output")
    parser.add_argument("--aws-region", default="us-east-1")
    parser.add_argument("--service-id")
    parser.add_argument("--service-region")
    parser.add_argument("--limit", type=int, default=25)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    params = {"limit": args.limit}
    if args.service_id or args.service_region:
        params.update(
            {
                "service_id": args.service_id or "",
                "region": args.service_region or "",
            }
        )
    url = args.api_url.rstrip("/") + "/incidents?" + urlencode(params)
    response = signed_request("GET", url, args.aws_region)
    print(response.status_code)
    print(response.text)
    return 0 if response.ok else 1


if __name__ == "__main__":
    sys.exit(main())

