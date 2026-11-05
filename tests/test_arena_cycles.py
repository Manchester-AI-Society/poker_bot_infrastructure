"""Timed cycles: every pairing replayed each round, results pooled."""

from __future__ import annotations

import json
import math
import random
import sqlite3

import pytest

from arena import leaderboard
from arena.export import ExportOptions, export_site
from arena.intake import submit
from arena.scheduler import pair_seed, run_round
from arena.stats import mean_and_se, pool
from arena.store import Store
from tests.test_arena_competition import (
    CALLER,
    FOLDER,
    RAISER,
    make_bot,
    quick,
)


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "arena_data")


@pytest.fixture
def bots(tmp_path):
    base = tmp_path / "src"
    return {
        "caller": make_bot(base, "caller", CALLER),
        "folder": make_bot(base, "folder", FOLDER),
        "raiser": make_bot(base, "raiser", RAISER),
    }


# -- pooling is exactly "all the deals together" ------------------------


def runs_of(values, cuts):
    parts, last = [], 0
    for cut in cuts + [len(values)]:
        parts.append(values[last:cut])
        last = cut
    out = []
    for part in parts:
        mean, se = mean_and_se(part)
        out.append((len(part), mean, None if math.isinf(se) else se))
    return out


def test_pool_equals_the_statistics_of_all_deals_together():
    rng = random.Random(7)
    for _ in range(200):
        values = [rng.gauss(0.1, 2.0) for _ in range(rng.randint(4, 60))]
        cuts = sorted(rng.sample(range(1, len(values)), rng.randint(1, 3)))
        total, mean, se = pool(runs_of(values, cuts))
        want_mean, want_se = mean_and_se(values)
        assert total == len(values)
        assert mean == pytest.approx(want_mean)
        assert se == pytest.approx(want_se)


def test_pool_handles_runs_of_one_deal_and_empty_input():
    total, mean, se = pool([(1, 0.5, None), (1, 1.5, None)])
    assert (total, mean) == (2, 1.0)
    assert se == pytest.approx(mean_and_se([0.5, 1.5])[1])
    assert pool([]) == (0, None, math.inf)
    assert pool([(1, 2.0, None)]) == (1, 2.0, math.inf)


def test_pool_tightens_as_runs_are_added():
    rng = random.Random(3)
    values = [rng.gauss(0, 1) for _ in range(120)]
    one = pool(runs_of(values[:30], []))[2]
    four = pool(runs_of(values, [30, 60, 90]))[2]
    assert four < one


# -- seeds and the database ---------------------------------------------


def test_every_round_has_its_own_cards_and_round_zero_is_unchanged():
    base = pair_seed(1, "ladder", "aa", "bb")
    assert pair_seed(1, "ladder", "bb", "aa") == base
    assert pair_seed(1, "ladder", "aa", "bb", 0) == base
    rounds = {pair_seed(1, "ladder", "aa", "bb", r) for r in range(1, 50)}
    assert len(rounds) == 49 and base not in rounds


def test_a_pairing_can_be_queued_once_per_round(store):
    assert store.create_job("ladder", "a", "b", 5, 1, None, 1) is not None
    assert store.create_job("ladder", "a", "b", 5, 1, None, 1) is None
    assert store.create_job("ladder", "b", "a", 5, 2, None, 2) is not None


OLD_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL, freeze_id INTEGER,
    a_hash TEXT NOT NULL, b_hash TEXT NOT NULL,
    deals INTEGER NOT NULL, seed INTEGER NOT NULL,
    status TEXT NOT NULL, worker TEXT, error TEXT,
    created_at REAL NOT NULL, started_at REAL, finished_at REAL);
CREATE UNIQUE INDEX jobs_pair
    ON jobs(kind, IFNULL(freeze_id, 0), a_hash, b_hash)
    WHERE status != 'stale';
INSERT INTO jobs(kind, a_hash, b_hash, deals, seed, status, created_at)
    VALUES ('ladder', 'a', 'b', 5, 1, 'done', 1.0);
"""


def test_a_database_from_before_cycles_is_upgraded_in_place(tmp_path):
    root = tmp_path / "old"
    (root).mkdir()
    conn = sqlite3.connect(root / "arena.sqlite")
    conn.executescript(OLD_SCHEMA)
    conn.close()

    store = Store(root)
    assert store.last_round("ladder") == 0  # the old job is round 0
    # The old rule (one per pairing) is gone; a new round may repeat it.
    assert store.create_job("ladder", "a", "b", 5, 9, None, 1) is not None
    # And opening it again is harmless.
    Store(root)
    assert store.create_job("ladder", "a", "b", 5, 9, None, 1) is None


# -- pooled results, hidden until the round is whole -------------------


def finish(store, round, a, b, mean, se, deals=10, faults=0, hands=None):
    job = store.create_job("ladder", a, b, deals, round, None, round)
    data = {
        "a": "A",
        "b": "B",
        "deals_requested": deals,
        "deals_completed": deals,
        "mean_bb": mean,
        "se_bb": se,
        "ci95_bb": 1.0,
        "hands_played": deals * 2,
        "faults_a": faults,
        "faults_b": 0,
        "disabled_a": None,
        "disabled_b": None,
        "think_a": 1.0,
        "think_b": 1.0,
        "elapsed": 2.0,
        "status": "complete",
    }
    store.finish_job(job, data, hands)
    return job


@pytest.fixture
def versions(store, bots):
    for name in ("caller", "raiser"):
        submit(store, name, str(bots[name]))
    return sorted(v.hash for v in store.current_versions())


def test_results_pool_the_rounds_of_a_pairing(store, versions):
    a, b = versions
    finish(store, 0, a, b, mean=0.2, se=0.1, faults=1)
    finish(store, 1, a, b, mean=0.4, se=0.1, faults=2)
    [row] = store.results("ladder")
    assert row["rounds"] == 2
    assert row["deals_completed"] == 20
    assert row["mean_bb"] == pytest.approx(0.3)
    assert row["faults_a"] == 3
    assert row["hands_played"] == 40
    # Twice the deals, so the interval is tighter than either round alone.
    assert row["se_bb"] < 0.1 * 1.01 and row["ci95_bb"] is not None


def test_a_round_in_progress_is_hidden_until_it_finishes(store, versions):
    a, b = versions
    finish(store, 1, a, b, mean=0.2, se=0.1)
    store.finish_round(0)  # cycling started; round 1 not done
    assert store.results("ladder") == []
    store.finish_round(1)
    assert [r["rounds"] for r in store.results("ladder")] == [1]
    # Without cycling nothing is hidden (the plain ladder is unchanged).
    plain = Store(store.root.parent / "plain")
    assert plain.cycle_done() is None


def test_the_leaderboard_reports_the_cycle(store, versions):
    a, b = versions
    finish(store, 1, a, b, mean=0.2, se=0.1)
    assert leaderboard.compute(store, "ladder")["cycle"] is None
    store.finish_round(1)
    assert leaderboard.compute(store, "ladder")["cycle"] == 1


def test_only_the_newest_rounds_hands_are_kept(store, versions):
    a, b = versions
    paths = []
    for round in (1, 2, 3):
        rel = f"hands/ladder-{round}.jsonl.gz"
        (store.root / rel).write_bytes(b"x")
        paths.append(rel)
        finish(store, round, a, b, mean=0.1 * round, se=0.1, hands=rel)
    store.finish_round(3)
    before = store.results("ladder")[0]["mean_bb"]

    assert store.prune_old_hands("ladder") == 2
    assert [(store.root / p).exists() for p in paths] == [False, False, True]
    [row] = store.results("ladder")
    assert row["hands_path"] == paths[2]
    assert row["mean_bb"] == pytest.approx(before)  # scores untouched
    assert store.prune_old_hands("ladder") == 0


# -- a real cycle with real bots ---------------------------------------


def test_cycles_replay_everything_on_fresh_cards_and_pool(store, bots):
    for name in ("caller", "folder", "raiser"):
        submit(store, name, str(bots[name]))
    settings = quick(deals=6)

    first, played = run_round(store, settings)
    assert (first, played) == (1, 3)
    board = leaderboard.compute(store, "ladder")
    assert board["cycle"] == 1 and board["pairs_done"] == 3
    one = {
        (r["a_hash"], r["b_hash"]): r["mean_bb"]
        for r in store.results("ladder")
    }

    second, played = run_round(store, settings)
    assert (second, played) == (2, 3)  # ALL pairings again, not just new
    rows = store.results("ladder")
    assert [r["rounds"] for r in rows] == [2, 2, 2]
    assert all(r["deals_completed"] == 12 for r in rows)
    # Fresh cards: the caller-vs-raiser result is not a repeat of round 1.
    seeds = {job_seed(store, jid) for jid in range(1, 7)}
    assert len(seeds) == 6
    # The folder loses exactly 3/4 bb a hand whatever the cards.
    folder = {
        t["team"]: t for t in leaderboard.compute(store, "ladder")["teams"]
    }
    assert folder["folder"]["score"] == pytest.approx(-0.75)
    assert one  # round one had results of its own
    # Only the newest round's hands remain.
    kept = sorted((store.root / "hands").glob("ladder-*.jsonl.gz"))
    assert len(kept) == 3


def job_seed(store, job_id):
    return store.get_job(job_id).seed


def test_a_new_bot_joins_at_the_next_round(store, bots):
    for name in ("caller", "folder"):
        submit(store, name, str(bots[name]))
    run_round(store, quick(deals=4))
    submit(store, "raiser", str(bots["raiser"]))

    run_round(store, quick(deals=4))
    rows = {
        (r["a_hash"], r["b_hash"]): r["rounds"]
        for r in store.results("ladder")
    }
    assert sorted(rows.values()) == [1, 1, 2]  # old pair twice, new pairs once
    board = leaderboard.compute(store, "ladder")
    assert board["pairs_done"] == 3


# -- what the site is given --------------------------------------------


def test_the_export_lists_one_entry_per_pairing_with_its_rounds(
    store, bots, tmp_path
):
    for name in ("caller", "folder"):
        submit(store, name, str(bots[name]))
    for _ in range(3):
        run_round(store, quick(deals=4))
    out = tmp_path / "site"
    export_site(store.root, out, ExportOptions())

    pairings = json.loads((out / "data" / "pairings-ladder.json").read_text())
    entries = pairings["pairings"] if isinstance(pairings, dict) else pairings
    assert len(entries) == 1
    assert entries[0]["rounds"] == 3 and entries[0]["deals_completed"] == 12
    board = json.loads((out / "data" / "leaderboard-ladder.json").read_text())
    assert board["cycle"] == 3


# -- the command ---------------------------------------------------------


def test_ladder_cycle_once_plays_a_round_and_reports_it(
    store, bots, tmp_path, capsys
):
    from arena.cli import main

    folder = tmp_path / "subs"
    for name in ("caller", "folder"):
        (folder / name).mkdir(parents=True)
        source = (bots[name] / "bot.py").read_text()
        (folder / name / "bot.py").write_text(source)
    code = main(
        [
            "ladder",
            "--root",
            str(store.root),
            "--submissions",
            str(folder),
            "--cycle",
            "30",
            "--once",
            "--deals",
            "4",
            "--workers",
            "2",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "[cycle 1] 1 pairings played" in out
    assert Store(store.root).cycle_done() == 1


def test_ladder_cycle_must_be_positive(store, capsys):
    from arena.cli import main

    assert main(["ladder", "--root", str(store.root), "--cycle", "0"]) == 2
    assert "above zero" in capsys.readouterr().out
