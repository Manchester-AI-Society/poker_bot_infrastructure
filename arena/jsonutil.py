"""JSON helpers shared by everything that writes files for a browser.

Python's ``json`` happily writes ``Infinity`` and ``NaN``, which are not
valid JSON: ``JSON.parse`` in a browser rejects the whole file. A pairing
with too few deals has an infinite confidence interval, so anything the
frontend reads goes through ``clean`` first.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def clean(value: Any) -> Any:
    """Returns ``value`` with every non-finite float replaced by None."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    return value


def dumps(value: Any, *, indent: int | None = None) -> str:
    """Serialises ``value`` as strictly valid JSON."""
    return json.dumps(
        clean(value),
        indent=indent,
        allow_nan=False,
        separators=None if indent else (",", ":"),
    )


def write_atomic(path: Path, text: str) -> None:
    """Writes ``text`` so a reader never sees a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
