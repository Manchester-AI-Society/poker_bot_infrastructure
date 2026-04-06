import os
from typing import Dict

DEFAULT_API_KEYS: Dict[str, str] = {
    "dev-key-1": "dev-bot-1",
    "dev-key-2": "dev-bot-2",
    "dev-key-3": "dev-bot-3",
}

DEFAULT_ADMIN_API_KEYS: Dict[str, str] = {
    "admin-dev-key": "admin-dev",
}


def _parse_key_mapping(raw_value: str) -> Dict[str, str]:
    """Parses bot-style key mappings from environment configuration.

    Args:
        raw_value (str): Comma-separated mapping formatted as id:key pairs.

    Returns:
        Dict[str, str]: Mapping from key to identifier.
    """
    key_mapping: Dict[str, str] = {}
    chunks = [chunk.strip() for chunk in raw_value.split(",") if chunk.strip()]
    for chunk in chunks:
        if ":" not in chunk:
            continue
        identifier, key = chunk.split(":", 1)
        identifier = identifier.strip()
        key = key.strip()
        if identifier and key:
            key_mapping[key] = identifier
    return key_mapping


def load_api_keys() -> Dict[str, str]:
    """Loads bot API keys from environment configuration.

    Args:
        None: This function does not take external arguments.

    Returns:
        Dict[str, str]: Mapping from API key to bot identifier.
    """

    raw = os.getenv("BOT_API_KEYS", "").strip()
    if not raw:
        return dict(DEFAULT_API_KEYS)

    api_keys = _parse_key_mapping(raw)

    return api_keys or dict(DEFAULT_API_KEYS)


def load_admin_api_keys() -> Dict[str, str]:
    """Loads admin API keys from environment configuration.

    Args:
        None: This function does not take external arguments.

    Returns:
        Dict[str, str]: Mapping from API key to admin identifier.
    """
    raw = os.getenv("ADMIN_API_KEYS", "").strip()
    if not raw:
        return dict(DEFAULT_ADMIN_API_KEYS)

    admin_keys = _parse_key_mapping(raw)

    return admin_keys or dict(DEFAULT_ADMIN_API_KEYS)
