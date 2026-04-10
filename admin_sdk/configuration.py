import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


@dataclass
class AdminSDKConfiguration:
    """Stores configuration values used by the admin SDK client."""

    base_url: str
    admin_api_key: str
    timeout_seconds: float = 10.0

    @classmethod
    def from_environment(
        cls,
        *,
        base_url_env: str = "POKER_SERVER_URL",
        admin_key_env: str = "POKER_ADMIN_API_KEY",
        timeout_env: str = "POKER_ADMIN_TIMEOUT_SECONDS",
        default_base_url: str = "http://127.0.0.1:8000",
    ) -> "AdminSDKConfiguration":
        """Builds configuration values from environment variables.

        Args:
            base_url_env (str): Environment variable containing the server base URL.
            admin_key_env (str): Environment variable containing the admin API key.
            timeout_env (str): Environment variable containing request timeout.
            default_base_url (str): Fallback base URL when not set in environment.

        Returns:
            AdminSDKConfiguration: Configuration loaded from environment values.
        """
        # Load .env automatically when present so scripts do not rely on shell exports.
        load_dotenv()
        base_url = os.getenv(base_url_env, default_base_url).strip()
        admin_api_key = os.getenv(admin_key_env, "").strip()
        timeout_raw: Optional[str] = os.getenv(timeout_env)
        timeout_seconds = 10.0
        if timeout_raw:
            try:
                timeout_seconds = float(timeout_raw)
            except ValueError:
                timeout_seconds = 10.0
        return cls(
            base_url=base_url,
            admin_api_key=admin_api_key,
            timeout_seconds=timeout_seconds,
        )
