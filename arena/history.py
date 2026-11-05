"""Hand-history files: gzip-compressed JSON lines, one hand per line."""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterator


class HandWriter:
    """Context manager that writes a ``.jsonl.gz`` and publishes it whole.

    Hands go to a private temporary file next to the target and are moved
    into place only when the run finishes, so a reader never sees a half
    written file, a crashed run never damages a good one, and two writers for
    the same path each finish a complete file instead of interleaving.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._temp = self.path.with_name(
            f"{self.path.name}.{os.getpid()}.{id(self):x}.part"
        )
        self._handle = None

    def __enter__(self) -> "HandWriter":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = gzip.open(self._temp, "wt", encoding="utf-8")
        return self

    def write(self, hand: Dict[str, Any]) -> None:
        self._handle.write(json.dumps(hand, separators=(",", ":")) + chr(10))

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._handle is None:
            return
        try:
            self._handle.close()
        finally:
            self._handle = None
        if exc_type is None:
            os.replace(self._temp, self.path)
        else:
            self._temp.unlink(missing_ok=True)


def read_hands(path: Path) -> Iterator[Dict[str, Any]]:
    """Yields the hand records stored in ``path``."""
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)
