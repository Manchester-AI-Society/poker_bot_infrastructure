"""Loads a team's bot from a Python file."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from .bot_interface import PokerBot


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
