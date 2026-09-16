from __future__ import annotations

import json
from typing import Any

import boto3
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest


def signed_request(
    method: str,
    url: str,
    region: str,
    payload: dict[str, Any] | None = None,
    timeout: int = 15,
) -> requests.Response:
    body = json.dumps(payload) if payload is not None else None
    credentials = boto3.Session().get_credentials()
    if credentials is None:
        raise RuntimeError("No AWS credentials were found")

    headers = {"Content-Type": "application/json"} if body else {}
    request = AWSRequest(method=method, url=url, data=body, headers=headers)
    SigV4Auth(credentials.get_frozen_credentials(), "execute-api", region).add_auth(request)
    return requests.request(
        method,
        url,
        data=body,
        headers=dict(request.headers),
        timeout=timeout,
    )

