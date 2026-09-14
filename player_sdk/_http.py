from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


class PlayerSDKError(RuntimeError):
    """Raised when a player SDK request fails."""


class PlayerSDKAuthError(PlayerSDKError):
    """Raised when the server rejects the provided API key."""


class PlayerSDKBadRequestError(PlayerSDKError):
    """Raised when the server rejects a request (e.g. stale turn)."""


def http_json(
    base_url: str,
    method: str,
    path: str,
    *,
    payload: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout_seconds: float = 10.0,
) -> Dict[str, Any]:
    """Sends an HTTP request and returns the parsed JSON object.

    Args:
        base_url (str): Server base URL without trailing slash.
        method (str): HTTP method value.
        path (str): API path appended to the base URL.
        payload (Optional[Dict[str, Any]]): JSON payload for request body.
        headers (Optional[Dict[str, str]]): Extra request headers.
        timeout_seconds (float): Request timeout in seconds.

    Returns:
        Dict[str, Any]: Parsed JSON object response.
    """
    url = f"{base_url.rstrip('/')}{path}"

    request_headers = {"Accept": "application/json"}
    if headers:
        request_headers.update(headers)

    body = None
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")

    request_obj = urllib.request.Request(
        url=url,
        data=body,
        method=method.upper(),
        headers=request_headers,
    )

    try:
        with urllib.request.urlopen(
            request_obj, timeout=timeout_seconds
        ) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code in {401, 403}:
            raise PlayerSDKAuthError(
                f"HTTP {exc.code} for {method} {path}: {detail}"
            ) from exc
        if exc.code == 400:
            raise PlayerSDKBadRequestError(
                f"HTTP {exc.code} for {method} {path}: {detail}"
            ) from exc
        raise PlayerSDKError(
            f"HTTP {exc.code} for {method} {path}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise PlayerSDKError(
            f"Could not reach server for {method} {path}: {exc}"
        ) from exc

    if not raw:
        return {}
    parsed = json.loads(raw)
    if isinstance(parsed, dict):
        return parsed
    raise PlayerSDKError(f"Expected JSON object response from {method} {path}")
