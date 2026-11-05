"""Competition flow: intake, versioning, ladder, freeze and final."""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

import pytest

from arena import leaderboard
from arena.intake import SubmissionError, scan_directory, submit
from arena.scheduler import (
    Settings,
    enqueue_final,
    enqueue_ladder,
    freeze_submissions,
    run_pending,
)
from arena.store import Store

HEADER = (
    "from player_sdk.bot_interface import PokerBot\n"
    "from player_sdk.models import Action\n"
)

CALLER = """
class Caller(PokerBot):
    def act(self, game_state):
        return Action.call()
"""

FOLDER = """
class Folder(PokerBot):
    def act(self, game_state):
        return Action.fold()
"""

RAISER = """
class Raiser(PokerBot):
    def act(self, game_state):
        if game_state.can_raise or game_state.can_bet:
            return Action.raise_to(game_state.min_raise_to)
        return Action.call()
"""

BROKEN = """
class Broken(PokerBot):
    def act(self, game_state):
        raise RuntimeError("bad bot")
"""


def make_bot(base, name, body):
    folder = base / name
    folder.mkdir(parents=True)
    (folder / "bot.py").write_text(HEADER + textwrap.dedent(body))
    return folder


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
        "broken": make_bot(base, "broken", BROKEN),
    }


def quick(deals=8, workers=2):
    return Settings(deals=deals, workers=workers, time_cap_seconds=120)


def test_valid_submission_becomes_current_and_broken_one_does_not(store, bots):
    good = submit(store, "caller", str(bots["caller"]))
    assert good.status == "valid"
    assert store.current_hash("caller") == good.digest

    bad = submit(store, "broken", str(bots["broken"]))
    assert bad.status == "invalid"
    assert "bad bot" in bad.message
    assert store.current_hash("broken") is None


def test_identical_resubmission_is_a_no_op_and_changes_make_new_versions(
    store, bots
):
    first = submit(store, "caller", str(bots["caller"]))
    again = submit(store, "caller", str(bots["caller"]))
    assert again.status == "unchanged" and again.digest == first.digest

    # A broken update never replaces the working version ...
    (bots["caller"] / "bot.py").write_text(HEADER + textwrap.dedent(BROKEN))
    broken = submit(store, "caller", str(bots["caller"]))
    assert broken.status == "invalid"
    assert store.current_hash("caller") == first.digest

    # ... a fixed one does.
    (bots["caller"] / "bot.py").write_text(HEADER + textwrap.dedent(RAISER))
    fixed = submit(store, "caller", str(bots["caller"]))
    assert fixed.status == "valid" and fixed.digest != first.digest
    assert store.current_hash("caller") == fixed.digest
    assert len(store.versions_of("caller")) == 3


def test_copying_another_teams_code_is_rejected(store, bots):
    submit(store, "caller", str(bots["caller"]))
    with pytest.raises(SubmissionError, match="already submitted"):
        submit(store, "copycat", str(bots["caller"]))


def test_bad_team_names_and_missing_bot_py_are_rejected(store, bots, tmp_path):
    with pytest.raises(SubmissionError, match="team names"):
        submit(store, "Bad Name!", str(bots["caller"]))
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(SubmissionError, match="bot.py"):
        submit(store, "empty", str(empty))
    with pytest.raises(SubmissionError, match="not found"):
        submit(store, "ghost", str(tmp_path / "nope"))


def test_single_file_submission_is_accepted(store, tmp_path):
    single = tmp_path / "mybot.py"
    single.write_text(HEADER + textwrap.dedent(CALLER))
    assert submit(store, "solo", str(single)).status == "valid"


def test_scan_directory_picks_up_new_and_changed_bots_once(
    store, bots, tmp_path
):
    watched = tmp_path / "submissions"
    shutil.copytree(bots["caller"], watched / "alpha")
    shutil.copytree(bots["folder"], watched / "beta")

    first = scan_directory(store, watched)
    assert sorted(r.team for r in first) == ["alpha", "beta"]
    assert scan_directory(store, watched) == []  # nothing changed

    (watched / "alpha" / "bot.py").write_text(HEADER + textwrap.dedent(RAISER))
    second = scan_directory(store, watched)
    assert [r.team for r in second] == ["alpha"]


def test_queue_only_adds_pairings_for_new_versions(store, bots):
    for name in ("caller", "folder", "raiser"):
        submit(store, name, str(bots[name]))
    assert enqueue_ladder(store, deals=8) == 3
    assert enqueue_ladder(store, deals=8) == 0  # nothing new

    (bots["caller"] / "bot.py").write_text(
        HEADER + textwrap.dedent(RAISER).replace("Raiser", "Raiser2")
    )
    submit(store, "caller", str(bots["caller"]))
    # Only the two pairings that include the new caller version.
    assert enqueue_ladder(store, deals=8) == 2


def test_stale_ladder_jobs_are_discarded_not_run(store, bots):
    for name in ("caller", "folder"):
        submit(store, name, str(bots[name]))
    enqueue_ladder(store, deals=8)
    (bots["caller"] / "bot.py").write_text(HEADER + textwrap.dedent(RAISER))
    submit(store, "caller", str(bots["caller"]))

    assert store.claim_job("t", ("ladder",)) is None  # old pair is stale
    assert store.job_counts("ladder") == {"stale": 1}


def test_ladder_ranks_bots_and_scores_a_folder_at_exactly_minus_three_quarters(
    store, bots
):
    for name in ("caller", "folder", "raiser"):
        submit(store, name, str(bots[name]))
    enqueue_ladder(store, deals=8)

    finished = run_pending(store, quick(), kinds=("ladder",))
    assert finished == 3
    assert store.job_counts("ladder") == {"done": 3}

    board = leaderboard.compute(store, "ladder")
    assert board["provisional"] is True
    assert board["pairs_done"] == board["pairs_total"] == 3
    teams = {t["team"]: t for t in board["teams"]}
    assert board["teams"][-1]["team"] == "folder"
    assert teams["folder"]["score"] == pytest.approx(-0.75)
    assert teams["folder"]["losses"] == 2
    # Zero-sum: scores average to zero across the field.
    assert sum(t["score"] for t in board["teams"]) == pytest.approx(0)
    # Matrix is antisymmetric.
    cell = board["matrix"]["caller"]["raiser"]["mean_bb"]
    other = board["matrix"]["raiser"]["caller"]["mean_bb"]
    assert cell == pytest.approx(-other)
    assert "FINAL" not in leaderboard.format_table(board)


def test_hand_histories_and_logs_are_stored_per_pairing(store, bots):
    from arena.history import read_hands

    for name in ("caller", "raiser"):
        submit(store, name, str(bots[name]))
    enqueue_ladder(store, deals=5)
    run_pending(store, quick(5, 1), kinds=("ladder",))

    (row,) = store.results("ladder")
    hands = list(read_hands(store.root / row["hands_path"]))
    assert len(hands) == 10
    assert all(sum(h["net"]) == 0 for h in hands)
    assert (store.root / "logs" / "caller").is_dir()


def test_freeze_then_final_ignores_later_submissions(store, bots):
    for name in ("caller", "folder", "raiser"):
        submit(store, name, str(bots[name]))
    freeze_id, excluded = freeze_submissions(store)
    assert excluded == []
    frozen = {v.team: v.hash for v in store.freeze_members(freeze_id)}
    assert set(frozen) == {"caller", "folder", "raiser"}

    # A new version arriving after the freeze does not affect the final.
    (bots["caller"] / "bot.py").write_text(
        HEADER + textwrap.dedent(RAISER).replace("Raiser", "Late")
    )
    submit(store, "caller", str(bots["caller"]))

    assert enqueue_final(store, freeze_id, deals=6) == 3
    run_pending(store, quick(6), kinds=("final",))
    board = leaderboard.compute(store, "final", freeze_id)
    assert board["provisional"] is False
    assert board["pairs_done"] == 3
    versions = {t["team"]: t["version"] for t in board["teams"]}
    assert versions == frozen
    assert board["teams"][-1]["team"] == "folder"
    assert "FINAL" in leaderboard.format_table(board)


def test_freeze_leaves_out_a_bot_that_no_longer_passes(store, bots):
    for name in ("caller", "folder"):
        submit(store, name, str(bots[name]))
    # Break the stored copy after it was accepted.
    stored = store.current_versions()[0]
    (Path(stored.path) / "bot.py").write_text(HEADER + textwrap.dedent(BROKEN))

    freeze_id, excluded = freeze_submissions(store)
    assert [team for team, _ in excluded] == [stored.team]
    assert [v.team for v in store.freeze_members(freeze_id)] == [
        v.team for v in store.current_versions() if v.team != stored.team
    ]


def test_a_crashing_job_is_marked_failed_and_can_be_retried(store, bots):
    for name in ("caller", "folder"):
        submit(store, name, str(bots[name]))
    enqueue_ladder(store, deals=5)
    shutil.rmtree(store.current_versions()[0].path)  # simulate corruption

    run_pending(store, quick(5, 1), kinds=("ladder",))
    assert store.job_counts("ladder") == {"failed": 1}

    assert store.requeue_failed() == 1
    assert enqueue_ladder(store, deals=5) == 1  # can be queued again


def test_running_jobs_left_by_a_dead_scheduler_are_requeued(store, bots):
    for name in ("caller", "folder"):
        submit(store, name, str(bots[name]))
    enqueue_ladder(store, deals=5)
    job = store.claim_job("dead-scheduler", ("ladder",))
    assert job is not None and store.job_counts("ladder") == {"running": 1}

    run_pending(store, quick(5, 1), kinds=("ladder",))
    assert store.job_counts("ladder") == {"done": 1}


def test_a_stale_log_that_cannot_be_deleted_does_not_fail_the_pairing(
    store, bots, monkeypatch
):
    """On Windows a log held open by an orphaned bot process (left by a forced
    stop of an earlier run) cannot be deleted; that used to fail the job with
    PermissionError."""
    from arena.scheduler import execute_job

    for name in ("caller", "folder"):
        submit(store, name, str(bots[name]))
    enqueue_ladder(store, deals=4)
    job = store.claim_job("test-worker", ("ladder",))
    for team in ("caller", "folder"):
        folder = next(store.root.joinpath("logs", team).iterdir())
        (folder / "ladder-vs-folder.log").write_text("old")
        (folder / "ladder-vs-caller.log").write_text("old")

    original = Path.unlink

    def locked(self, *args, **kwargs):
        if self.suffix == ".log":
            raise PermissionError(13, "being used by another process")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked)

    execute_job(str(store.root), job.id, quick(4, 1))  # must not raise

    assert store.results("ladder")
