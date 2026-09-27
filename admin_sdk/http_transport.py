import json
from typing import Any, Dict, Optional
from urllib import error, request

from .configuration import AdminSDKConfiguration
from .exceptions import AdminSDKAuthenticationError, AdminSDKRequestError


class AdminHTTPTransport:
    """Performs HTTP requests for admin SDK operations."""

    def __init__(self, configuration: AdminSDKConfiguration) -> None:
        """Initialises the HTTP transport.

        Args:
            configuration (AdminSDKConfiguration): Client configuration values.

        Returns:
            None: This function does not return a value.
        """
        self._configuration = configuration

    def request_json(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        api_key_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Sends an HTTP request and returns parsed JSON.

        Args:
            method (str): HTTP method value.
            path (str): API path appended to the base URL.
            payload (Optional[Dict[str, Any]]): JSON payload for request body.
            api_key_override (Optional[str]): Optional key override.

        Returns:
            Dict[str, Any]: Parsed JSON response mapping.
        """
        base_url = self._configuration.base_url.rstrip("/")
        url = f"{base_url}{path}"
        data: Optional[bytes] = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")

        api_key = (
            api_key_override or self._configuration.admin_api_key
        ).strip()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Admin-Key": api_key,
            "Authorization": f"Bearer {api_key}",
        }

        req = request.Request(
            url=url, data=data, method=method.upper(), headers=headers
        )

        try:
            timeout = self._configuration.timeout_seconds
            with request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                if not raw:
                    return {}
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
                raise AdminSDKRequestError(
                    "Server response was not a JSON object"
                )
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code in {401, 403}:
                raise AdminSDKAuthenticationError(
                    body or "Admin authentication failed"
                ) from exc
            raise AdminSDKRequestError(f"HTTP {exc.code}: {body}") from exc
        except error.URLError as exc:
            raise AdminSDKRequestError(
                f"Could not reach server: {exc}"
            ) from exc
