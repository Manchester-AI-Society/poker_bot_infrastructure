"""The files a browser reads must be strictly valid JSON."""

import json
import math

from arena.jsonutil import clean, dumps, write_atomic
from arena.leaderboard import write_json


def test_non_finite_numbers_become_null():
    payload = {"a": math.inf, "b": [1.5, -math.inf, math.nan], "c": {"d": 2}}

    assert clean(payload) == {"a": None, "b": [1.5, None, None], "c": {"d": 2}}


def test_dumps_is_strict_json_that_a_browser_would_accept():
    text = dumps({"ci": math.inf, "mean": 0.25})

    # JSON.parse rejects Infinity/NaN, so they must not appear at all.
    assert "Infinity" not in text and "NaN" not in text
    assert json.loads(text) == {"ci": None, "mean": 0.25}


def test_leaderboard_file_with_an_infinite_interval_is_valid_json(tmp_path):
    board = {
        "teams": [],
        "matrix": {"a": {"b": {"mean_bb": 0.1, "ci95_bb": math.inf}}},
    }
    path = tmp_path / "results" / "leaderboard.json"

    write_json(board, path)

    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["matrix"]["a"]["b"]["ci95_bb"] is None
    assert not list(path.parent.glob("*.tmp"))


def test_write_atomic_replaces_the_file_and_leaves_no_temp_file(tmp_path):
    target = tmp_path / "x.json"
    write_atomic(target, "1")
    write_atomic(target, "2")

    assert target.read_text(encoding="utf-8") == "2"
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]
