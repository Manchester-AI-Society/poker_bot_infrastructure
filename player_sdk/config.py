from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


@dataclass
class PlayerConfig:
    """Connection settings for a bot joining a remote match."""

    base_url: str
    api_key: str
    match_id: Optional[str] = None
    player_id: Optional[str] = None
    timeout_seconds: float = 10.0

    @classmethod
    def from_environment(
        cls,
        *,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        match_id: Optional[str] = None,
        player_id: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        base_url_env: str = "POKER_SERVER_URL",
        api_key_env: str = "POKER_API_KEY",
        match_id_env: str = "POKER_MATCH_ID",
        player_id_env: str = "POKER_PLAYER_ID",
        timeout_env: str = "POKER_TIMEOUT_SECONDS",
        default_base_url: str = "http://127.0.0.1:8000",
    ) -> "PlayerConfig":
        """Builds player configuration from arguments and environment.

        Only the server URL and API key are required; explicit keyword
        arguments take precedence over environment variables, and the
        match and player identity are auto-discovered when omitted.

        Args:
            base_url (Optional[str]): Explicit server base URL.
            api_key (Optional[str]): Explicit API key.
            match_id (Optional[str]): Explicit match identifier.
            player_id (Optional[str]): Explicit player identifier.
            timeout_seconds (Optional[float]): Explicit request timeout.
            base_url_env (str): Environment variable for the server URL.
            api_key_env (str): Environment variable for the API key.
            match_id_env (str): Environment variable for an explicit match.
            player_id_env (str): Environment variable for an explicit player.
            timeout_env (str): Environment variable for request timeout.
            default_base_url (str): Fallback base URL if env unset.

        Returns:
            PlayerConfig: Values loaded from the environment.

        Raises:
            ValueError: When the API key is not provided.
        """
        load_dotenv()
        base_url = (
            base_url or os.getenv(base_url_env, default_base_url).strip()
        )
        api_key = api_key or os.getenv(api_key_env, "").strip()
        match_id = match_id or os.getenv(match_id_env, "").strip() or None
        player_id = player_id or os.getenv(player_id_env, "").strip() or None
        if timeout_seconds is None:
            timeout_raw: Optional[str] = os.getenv(timeout_env)
            timeout_seconds = 10.0
            if timeout_raw:
                try:
                    timeout_seconds = float(timeout_raw)
                except ValueError:
                    timeout_seconds = 10.0

        if not api_key:
            raise ValueError(
                "The api_key option must be set either by passing"
                " api_key=... (e.g. to play()) or by setting the"
                f" {api_key_env} environment variable."
            )

        return cls(
            base_url=base_url,
            api_key=api_key,
            match_id=match_id,
            player_id=player_id,
            timeout_seconds=timeout_seconds,
        )
