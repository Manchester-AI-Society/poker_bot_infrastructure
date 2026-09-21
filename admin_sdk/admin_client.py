from typing import Any, Dict, Optional

from .configuration import AdminSDKConfiguration
from .http_transport import AdminHTTPTransport
from .models import EndMatchOptions, MatchCreationOptions


class AdminSDKClient:
    """Provides command-style admin operations for the poker server."""

    def __init__(self, configuration: AdminSDKConfiguration) -> None:
        """Initialises the admin SDK client.

        Args:
            configuration (AdminSDKConfiguration): Client configuration values.

        Returns:
            None: This function does not return a value.
        """
        self._configuration = configuration
        self._transport = AdminHTTPTransport(configuration)

    def create_match(
        self,
        options: MatchCreationOptions,
        api_key_being_used: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Creates a match with full admin configuration options.

        Args:
            options (MatchCreationOptions): Match creation options.
            api_key_being_used (Optional[str]): Optional key override.

        Returns:
            Dict[str, Any]: Mapping containing server response details.
        """
        if options.number_of_bots_allowed < 2:
            raise ValueError("number_of_bots_allowed must be at least 2")
        if len(options.player_ids) != options.number_of_bots_allowed:
            raise ValueError(
                "number_of_bots_allowed must match the number of player_ids"
            )

        payload = {
            "player_ids": list(options.player_ids),
            "starting_stack": options.starting_stack,
            "small_blind": options.small_blind,
            "big_blind": options.big_blind,
            "turn_timeout_seconds": options.turn_timeout_seconds,
            "event_log_limit": options.event_log_limit,
            "max_hands": options.max_hands,
            "wait_for_players": options.wait_for_players,
        }
        return self._transport.request_json(
            "POST",
            "/v1/matches",
            payload,
            api_key_override=api_key_being_used,
        )

    def start_match(
        self,
        match_id: str,
        force: bool = False,
        api_key_being_used: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Starts (or arms) a created match.

        Args:
            match_id (str): Match identifier.
            force (bool): Skip the player-readiness gate when True.
            api_key_being_used (Optional[str]): Optional key override.

        Returns:
            Dict[str, Any]: Mapping containing server response details.
        """
        force_flag = str(force).lower()
        return self._transport.request_json(
            "POST",
            f"/v1/matches/{match_id}/start?force={force_flag}",
            {},
            api_key_override=api_key_being_used,
        )

    def pause_match(
        self,
        match_id: str,
        reason: Optional[str] = None,
        api_key_being_used: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Pauses a running match.

        Args:
            match_id (str): Match identifier.
            reason (Optional[str]): Optional pause reason.
            api_key_being_used (Optional[str]): Optional key override.

        Returns:
            Dict[str, Any]: Mapping containing server response details.
        """
        return self._transport.request_json(
            "POST",
            f"/v1/matches/{match_id}/pause",
            {"reason": reason},
            api_key_override=api_key_being_used,
        )

    def resume_match(
        self,
        match_id: str,
        reason: Optional[str] = None,
        api_key_being_used: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Resumes a paused match.

        Args:
            match_id (str): Match identifier.
            reason (Optional[str]): Optional resume reason.
            api_key_being_used (Optional[str]): Optional key override.

        Returns:
            Dict[str, Any]: Mapping containing server response details.
        """
        return self._transport.request_json(
            "POST",
            f"/v1/matches/{match_id}/resume",
            {"reason": reason},
            api_key_override=api_key_being_used,
        )

    def end_match(
        self,
        match_id: str,
        options: Optional[EndMatchOptions] = None,
        api_key_being_used: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Ends an active match.

        Args:
            match_id (str): Match identifier.
            options (Optional[EndMatchOptions]): End options payload.
            api_key_being_used (Optional[str]): Optional key override.

        Returns:
            Dict[str, Any]: Mapping containing server response details.
        """
        opts = options or EndMatchOptions()
        payload = {"reason": opts.reason, "mode": opts.mode}
        return self._transport.request_json(
            "POST",
            f"/v1/matches/{match_id}/end",
            payload,
            api_key_override=api_key_being_used,
        )

    def get_full_match_state(
        self, match_id: str, api_key_being_used: Optional[str] = None
    ) -> Dict[str, Any]:
        """Gets full private match state for admin inspection.

        Args:
            match_id (str): Match identifier.
            api_key_being_used (Optional[str]): Optional key override.

        Returns:
            Dict[str, Any]: Mapping containing full private match state.
        """
        return self._transport.request_json(
            "GET",
            f"/v1/matches/{match_id}/full-state",
            None,
            api_key_override=api_key_being_used,
        )

    def get_match_admin_actions(
        self, match_id: str, api_key_being_used: Optional[str] = None
    ) -> Dict[str, Any]:
        """Gets admin action history for a match.

        Args:
            match_id (str): Match identifier.
            api_key_being_used (Optional[str]): Optional key override.

        Returns:
            Dict[str, Any]: Mapping containing admin action entries.
        """
        return self._transport.request_json(
            "GET",
            f"/v1/matches/{match_id}/admin-actions",
            None,
            api_key_override=api_key_being_used,
        )

    def create_player(
        self,
        player_id: str,
        api_key: Optional[str] = None,
        api_key_being_used: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Creates a player and API key mapping.

        Args:
            player_id (str): Player identifier.
            api_key (Optional[str]): Optional explicit API key to assign.
            api_key_being_used (Optional[str]): Optional key override.

        Returns:
            Dict[str, Any]: Mapping containing player creation results.
        """
        payload = {"player_id": player_id, "api_key": api_key}
        return self._transport.request_json(
            "POST",
            "/v1/admin/players",
            payload,
            api_key_override=api_key_being_used,
        )

    def list_players(
        self, api_key_being_used: Optional[str] = None
    ) -> Dict[str, Any]:
        """Lists all players and their API keys.

        Args:
            api_key_being_used (Optional[str]): Optional key override.

        Returns:
            Dict[str, Any]: Mapping containing player and key data.
        """
        return self._transport.request_json(
            "GET",
            "/v1/admin/players",
            None,
            api_key_override=api_key_being_used,
        )

    def delete_player(
        self, player_id: str, api_key_being_used: Optional[str] = None
    ) -> Dict[str, Any]:
        """Deletes a player and revokes all API keys.

        Args:
            player_id (str): Player identifier.
            api_key_being_used (Optional[str]): Optional key override.

        Returns:
            Dict[str, Any]: Mapping containing deletion results.
        """
        return self._transport.request_json(
            "DELETE",
            f"/v1/admin/players/{player_id}",
            None,
            api_key_override=api_key_being_used,
        )

    def rotate_player_key(
        self,
        player_id: str,
        api_key: Optional[str] = None,
        api_key_being_used: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Rotates the API key for a player.

        Args:
            player_id (str): Player identifier.
            api_key (Optional[str]): Optional explicit replacement key.
            api_key_being_used (Optional[str]): Optional key override.

        Returns:
            Dict[str, Any]: Mapping containing key rotation results.
        """
        payload = {"api_key": api_key}
        return self._transport.request_json(
            "POST",
            f"/v1/admin/players/{player_id}/rotate-key",
            payload,
            api_key_override=api_key_being_used,
        )
