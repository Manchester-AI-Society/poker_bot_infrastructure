from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Optional, Sequence

from ._ws import RealtimeBotRunner, RealtimeUnavailableError
from .bot_interface import PokerBot
from .client import PokerEngineClient
from .config import PlayerConfig
from .models import GameState

_VALID_TRANSPORTS = frozenset({"auto", "ws", "http"})


def play(
    model: PokerBot,
    *,
    api_key: str,
    server_url: str,
    match_id: str,
    player_id: Optional[str] = None,
    timeout_seconds: float = 10.0,
    transport: str = "auto",
    poll_interval_seconds: float = 0.5,
    verbose: bool = True,
) -> Optional[GameState]:
    """Plays a match with one call.

    ``api_key``, ``server_url``, and ``match_id`` are mandatory —
    pass them explicitly, in the style of naming a model in the
    OpenAI SDK:

        play(MyBot(), api_key="dev-key-1",
             server_url="http://host:8000", match_id="m_123")

    The player identity and seat are still auto-discovered from the
    API key and the match's players list.

    Args:
        model (PokerBot): Bot instance to play, e.g. ``play(MyBot(), ...)``.
        api_key (str): Bot API key (required).
        server_url (str): Server base URL (required).
        match_id (str): Match identifier (required).
        player_id (Optional[str]): Explicit player identity.
        timeout_seconds (float): HTTP request timeout.
        transport (str): ``"auto"`` (websocket with HTTP polling
            fallback), ``"ws"``, or ``"http"``.
        poll_interval_seconds (float): HTTP polling interval.
        verbose (bool): Prints progress and result summaries when True.

    Returns:
        Optional[GameState]: Final game state once the match finishes;
        ``state.summary`` gives a one-line human-readable result.

    Raises:
        ValueError: When any mandatory argument is empty.
        PlayerSDKAuthError: When the server rejects the API key.
    """
    for label, value in (
        ("api_key", api_key),
        ("server_url", server_url),
        ("match_id", match_id),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"{label} is mandatory and must be a non-empty string;"
                " pass it explicitly, e.g."
                f" play(model=MyBot(), {label}=...)"
            )

    configuration = PlayerConfig(
        base_url=server_url,
        api_key=api_key,
        match_id=match_id,
        player_id=player_id,
        timeout_seconds=timeout_seconds,
    )
    return _play(
        model,
        configuration,
        transport=transport,
        poll_interval_seconds=poll_interval_seconds,
        verbose=verbose,
    )


def run_bot(
    bot: PokerBot,
    *,
    config: Optional[PlayerConfig] = None,
    api_key: Optional[str] = None,
    server_url: Optional[str] = None,
    match_id: Optional[str] = None,
    player_id: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
    transport: str = "auto",
    poll_interval_seconds: float = 0.5,
    verbose: bool = True,
) -> Optional[GameState]:
    """Connects a bot to its match and plays until the match finishes.

    Only a server URL and API key are required; the player identity,
    match, and seat are auto-discovered from the server.

    Args:
        bot (PokerBot): Bot instance that provides actions.
        config (Optional[PlayerConfig]): Connection settings; loaded
            from the environment when omitted.
        api_key (Optional[str]): Bot API key.
        server_url (Optional[str]): Server base URL.
        match_id (Optional[str]): Match identifier.
        player_id (Optional[str]): Explicit player identity.
        timeout_seconds (Optional[float]): HTTP request timeout.
        transport (str): ``"auto"``, ``"ws"``, or ``"http"``.
        poll_interval_seconds (float): State polling interval.
        verbose (bool): Prints progress and result summaries when True.

    Returns:
        Optional[GameState]: Final game state once the match finishes.
    """
    configuration = config or PlayerConfig.from_environment(
        base_url=server_url,
        api_key=api_key,
        match_id=match_id,
        player_id=player_id,
        timeout_seconds=timeout_seconds,
    )
    return _play(
        bot,
        configuration,
        transport=transport,
        poll_interval_seconds=poll_interval_seconds,
        verbose=verbose,
    )


def _play(
    bot: PokerBot,
    configuration: PlayerConfig,
    *,
    transport: str,
    poll_interval_seconds: float,
    verbose: bool,
) -> Optional[GameState]:
    normalised = (transport or "auto").strip().lower()
    if normalised not in _VALID_TRANSPORTS:
        raise ValueError(
            "transport must be one of 'auto', 'ws', or 'http'"
            f" (got {transport!r})"
        )

    if normalised in {"auto", "ws"}:
        try:
            runner = RealtimeBotRunner(
                base_url=configuration.base_url,
                match_id=configuration.match_id or "",
                bot=bot,
                player_id=configuration.player_id,
                api_key=configuration.api_key,
                timeout_seconds=configuration.timeout_seconds,
                verbose=verbose,
            )
            return _finish(runner.run(), verbose=verbose)
        except RealtimeUnavailableError as exc:
            if normalised == "ws":
                raise
            if verbose:
                print(
                    "[player_sdk] Websocket unavailable"
                    f" ({exc}); using HTTP polling instead"
                )

    final_state = _run_over_http(
        bot,
        configuration,
        poll_interval_seconds=poll_interval_seconds,
        verbose=verbose,
    )
    return _finish(final_state, verbose=verbose)


def _run_over_http(
    bot: PokerBot,
    configuration: PlayerConfig,
    *,
    poll_interval_seconds: float,
    verbose: bool,
) -> Optional[GameState]:
    client = PokerEngineClient(
        base_url=configuration.base_url,
        match_id=configuration.match_id or "",
        bot=bot,
        player_id=configuration.player_id,
        api_key=configuration.api_key,
        timeout_seconds=configuration.timeout_seconds,
    )

    health = client.connect()
    if not health.get("ok"):
        raise RuntimeError("Server health check failed")

    player_id = client.resolve_identity()
    if not client.match_id:
        client.discover_match()

    if verbose:
        print(f"[player_sdk] Playing as {player_id} (http)")
        print(f"[player_sdk] Match: {client.match_id}")

    return client.run_forever(poll_interval_seconds=poll_interval_seconds)


def _finish(
    final_state: Optional[GameState], *, verbose: bool
) -> Optional[GameState]:
    if verbose and final_state is not None:
        _print_summary(final_state)
    return final_state


def load_bot_from_file(path: str | Path) -> PokerBot:
    """Loads and instantiates a PokerBot subclass from a Python file.

    Args:
        path (str | Path): Path to a module defining exactly one
            PokerBot subclass with a no-argument constructor.

    Returns:
        PokerBot: Instantiated bot.
    """
    module_path = Path(path)
    if not module_path.is_file():
        raise FileNotFoundError(f"Bot file not found: {module_path}")

    spec = importlib.util.spec_from_file_location(
        module_path.stem, module_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Python module: {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_path.stem] = module
    spec.loader.exec_module(module)

    from .bot_interface import PokerBot as BaseBot

    candidates = [
        obj
        for obj in vars(module).values()
        if isinstance(obj, type)
        and issubclass(obj, BaseBot)
        and obj is not BaseBot
        and obj.__module__ == module.__name__
    ]
    if len(candidates) != 1:
        names = [cls.__name__ for cls in candidates]
        raise RuntimeError(
            f"Expected exactly one PokerBot subclass in {module_path},"
            f" found: {names or 'none'}"
        )

    return candidates[0]()


def _print_summary(state: GameState) -> None:
    print("[player_sdk] Match finished.")
    print(f"[player_sdk] {state.summary}")


def main(argv: Optional[Sequence[str]] = None) -> None:
    """CLI entry point: run a bot file against a remote match.

    Args:
        argv (Optional[Sequence[str]]): Argument vector override.

    Returns:
        None: This function does not return a value.
    """
    parser = argparse.ArgumentParser(
        prog="python -m player_sdk.run_bot",
        description="Run a PokerBot subclass against a live match.",
    )
    parser.add_argument("bot_file", help="Path to a .py file defining a bot")
    parser.add_argument("--server-url", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--match-id", default=None)
    parser.add_argument(
        "--transport",
        default="auto",
        choices=("auto", "ws", "http"),
        help="Realtime websocket or HTTP polling transport",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="Seconds between state polls",
    )
    args = parser.parse_args(argv)

    config = PlayerConfig.from_environment(
        base_url=args.server_url or None,
        api_key=args.api_key,
        match_id=args.match_id,
    )

    bot = load_bot_from_file(args.bot_file)
    run_bot(
        bot,
        config=config,
        transport=args.transport,
        poll_interval_seconds=args.poll_interval,
    )


if __name__ == "__main__":
    main()
