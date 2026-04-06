import os
from typing import Dict

DEFAULT_API_KEYS: Dict[str, str] = {
    "dev-key-1": "dev-bot-1",
    "dev-key-2": "dev-bot-2",
    "dev-key-3": "dev-bot-3",
}


def load_api_keys() -> Dict[str, str]:
    """This just loads the API keys.

    Args:
        None: This function does not take external arguments.

    Returns:
        Dict[str, str]: Mapping produced by this function.
    """

    raw = os.getenv("BOT_API_KEYS", "").strip()
    if not raw:
        return dict(DEFAULT_API_KEYS)

    api_keys: Dict[str, str] = {}
    chunks = [chunk.strip() for chunk in raw.split(",") if chunk.strip()]
    for chunk in chunks:
        if ":" not in chunk:
            continue
        bot_id, key = chunk.split(":", 1)
        bot_id = bot_id.strip()
        key = key.strip()
        if bot_id and key:
            api_keys[key] = bot_id

    return api_keys or dict(DEFAULT_API_KEYS)
