"""Names registered on the website, read from the registration form's sheet.

The website's Register page checks a team name and then opens a small Google
Form (team name only) with the name filled in. The form's response sheet is
the only place those names are kept; the export reads it (a CSV file, or the
sheet's "published to the web" CSV address) and lists each name on the site:

* ``registered``  the name is in the registration sheet, but no bot with that
  name has been imported yet;
* ``submitted``   a bot with that name has been imported (it exists in the
  submissions), so the name is confirmed.

Registering is optional: a team that only uploads a bot still appears, as
``submitted``. Names are checked against the same rule as team names
everywhere else, so the sheet can hold anything and only valid names are used.
"""

from __future__ import annotations

import csv
import io
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

from .store import Store

TEAM_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
MAX_NAMES = 500
MAX_BYTES = 1024 * 1024
FETCH_TIMEOUT_SECONDS = 20
CACHE_KEY = "registrations_cache"

# The prefilled-link form the site sends people to: a Google Form's viewform
# address that ends in the entry that takes the team name.
REGISTER_FORM = re.compile(
    r"^https://docs\.google\.com/forms/d/e/[A-Za-z0-9_-]+/viewform\?"
    r"[^\s#]*entry\.\d+=$"
)


class RosterError(Exception):
    """The registration sheet could not be read."""


def parse_names(text: str) -> List[str]:
    """Valid, lowercase, de-duplicated team names from the sheet's CSV.

    The first row is the header; the column whose header mentions "team" is
    used (otherwise the second column, as in a Google Form's own sheet, where
    the first column is the timestamp). Order of first appearance is kept.
    """
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    if not rows:
        return []
    header, body = rows[0], rows[1:]
    column = next(
        (i for i, cell in enumerate(header) if "team" in cell.lower()),
        1 if len(header) > 1 else 0,
    )
    names: List[str] = []
    seen = set()
    for row in body:
        if column >= len(row):
            continue
        name = row[column].strip().lower()
        if TEAM_NAME.match(name) and name not in seen:
            seen.add(name)
            names.append(name)
            if len(names) >= MAX_NAMES:
                break
    return names


def _read(source: str) -> str:
    if source.startswith("https://"):
        request = urllib.request.Request(
            source, headers={"User-Agent": "poker-arena-roster"}
        )
        try:
            with urllib.request.urlopen(
                request, timeout=FETCH_TIMEOUT_SECONDS
            ) as response:
                data = response.read(MAX_BYTES + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RosterError(f"cannot read {source}: {exc}") from exc
    elif source.startswith(("http://", "ftp://", "file:")):
        raise RosterError("a registration address must start with https://")
    else:
        try:
            data = Path(source).read_bytes()
        except OSError as exc:
            raise RosterError(f"cannot read {source}: {exc}") from exc
    if len(data) > MAX_BYTES:
        raise RosterError("the registration sheet is too large")
    return data.decode("utf-8", errors="replace")


def load_registered(
    source: str, store: Optional[Store] = None
) -> Tuple[List[str], Optional[str]]:
    """The registered names, and a warning if the last good list is used.

    A sheet that cannot be read (the network dropped, the link changed) never
    blanks the roster: the last list that was read is used instead, and the
    warning says so.
    """
    if not source:
        return [], None
    try:
        names = parse_names(_read(source))
    except RosterError as exc:
        cached = store.meta_get(CACHE_KEY) if store else None
        if cached is None:
            raise
        return json.loads(cached), f"{exc}; using the last list that was read"
    if store is not None:
        store.meta_set(CACHE_KEY, json.dumps(names))
    return names, None


def roster(
    registered: List[str], submitted: List[str]
) -> List[Tuple[str, str]]:
    """Every name with its status, sorted: ``(name, status)``."""
    sent = set(submitted)
    everyone = sorted(set(registered) | sent)
    return [(n, "submitted" if n in sent else "registered") for n in everyone]
