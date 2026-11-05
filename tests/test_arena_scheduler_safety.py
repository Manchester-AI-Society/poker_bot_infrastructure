"""Two schedulers can share one results folder; neither may take the other's
running work, and a hand-history file is never seen half written."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

from arena.history import HandWriter, read_hands
from arena.intake import submit
from arena.procs import pid_alive, worker_pid
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


def make_bot(base, name, action):
    folder = base / name
    folder.mkdir(parents=True)
    (folder / "bot.py").write_text(
        HEADER
        + textwrap.dedent(
            f"""
            class B(PokerBot):
                def act(self, s):
                    return Action.{action}()
            """
        )
    )
    return folder


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "arena_data")
    for name, action in (("caller", "call"), ("folder", "fold")):
        submit(store, name, str(make_bot(tmp_path / "src", name, action)))
    return store


def dead_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


# -- is it alive? ------------------------------------------------------


def test_this_process_is_alive_and_a_finished_one_is_not():
    assert pid_alive(os.getpid())
    assert not pid_alive(dead_pid())


@pytest.mark.parametrize("pid", [0, -1, -4242])
def test_impossible_process_ids_are_not_alive(pid):
    assert not pid_alive(pid)


def test_the_process_id_is_read_from_a_worker_name():
    assert worker_pid("scheduler-4242") == 4242
    assert worker_pid("dead-scheduler") is None
    assert worker_pid(None) is None
    assert worker_pid("scheduler-") is None


# -- not taking a live scheduler's work --------------------------------


def test_a_job_running_under_a_live_scheduler_is_not_taken_away(store):
    enqueue_ladder(store, deals=4)
    job = store.claim_job(f"scheduler-{os.getpid()}", ("ladder",))

    released = store.requeue_running()

    assert released == 0
    assert store.job_counts("ladder") == {"running": 1}
    assert job is not None


def test_a_job_whose_scheduler_died_is_given_back(store):
    enqueue_ladder(store, deals=4)
    store.claim_job(f"scheduler-{dead_pid()}", ("ladder",))

    released = store.requeue_running()

    assert released == 1
    assert store.job_counts("ladder") == {"queued": 1}


def test_a_job_with_an_unreadable_owner_is_given_back(store):
    enqueue_ladder(store, deals=4)
    store.claim_job("some-worker", ("ladder",))

    assert store.requeue_running() == 1


def test_a_ladder_cycle_leaves_a_running_final_alone(store):
    """Regression. The ladder loop calls run_pending every few seconds, which
    used to put EVERY running job back in the queue, including a final being
    played at the same time, so the same pairing ran twice at once and wrote
    the same hand-history file (seen: 4 of 6 final files corrupted)."""
    freeze_id, _ = freeze_submissions(store)
    enqueue_final(store, freeze_id, deals=4)
    final = store.claim_job(f"scheduler-{os.getpid()}", ("final",))
    assert final is not None
    enqueue_ladder(store, deals=4)

    run_pending(
        store,
        Settings(deals=4, workers=1, time_cap_seconds=60),
        kinds=("ladder",),
    )

    assert store.job_counts("final") == {"running": 1}  # still the final's
    assert store.job_counts("ladder") == {"done": 1}


# -- hand histories are written atomically -----------------------------


def hand(index):
    return {"hand_index": index, "net": [0, 0]}


def test_a_finished_hand_file_is_complete_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "hands" / "x.jsonl.gz"

    with HandWriter(path) as writer:
        for index in range(5):
            writer.write(hand(index))

    assert [h["hand_index"] for h in read_hands(path)] == [0, 1, 2, 3, 4]
    assert [p.name for p in path.parent.iterdir()] == ["x.jsonl.gz"]


def test_the_file_does_not_exist_until_it_is_complete(tmp_path):
    path = tmp_path / "x.jsonl.gz"

    with HandWriter(path) as writer:
        writer.write(hand(0))
        assert not path.exists()  # a reader can never see a half-written file

    assert path.exists()


def test_a_failed_run_keeps_the_previous_complete_file(tmp_path):
    path = tmp_path / "x.jsonl.gz"
    with HandWriter(path) as writer:
        writer.write(hand(1))

    with pytest.raises(RuntimeError):
        with HandWriter(path) as writer:
            writer.write(hand(2))
            raise RuntimeError("the pairing crashed")

    assert [h["hand_index"] for h in read_hands(path)] == [1]
    assert [p.name for p in tmp_path.iterdir()] == ["x.jsonl.gz"]


def test_two_writers_for_the_same_file_never_interleave(tmp_path):
    path = tmp_path / "x.jsonl.gz"
    first, second = HandWriter(path), HandWriter(path)
    first.__enter__()
    second.__enter__()

    for index in range(50):
        first.write(hand(index))
        second.write(hand(1000 + index))
    first.__exit__(None, None, None)
    second.__exit__(None, None, None)

    indexes = [h["hand_index"] for h in read_hands(path)]
    # Whichever finished last wins, as a whole: never a mixture.
    assert indexes in (list(range(50)), [1000 + i for i in range(50)])
