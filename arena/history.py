"""Hand-history files: gzip-compressed JSON lines, one hand per line."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any, Dict, Iterator


class HandWriter:
    """Context manager that appends hand records to a ``.jsonl.gz``."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._handle = None

    def __enter__(self) -> "HandWriter":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = gzip.open(self.path, "wt", encoding="utf-8")
        return self

    def write(self, hand: Dict[str, Any]) -> None:
        self._handle.write(json.dumps(hand, separators=(",", ":")) + "\n")

    def __exit__(self, *exc_info) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None


def read_hands(path: Path) -> Iterator[Dict[str, Any]]:
    """Yields the hand records stored in ``path``."""
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)
