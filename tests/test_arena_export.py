"""The static site export: data files, replay policy and what stays private."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from arena.export import (
    ExportError,
    ExportOptions,
    disabled_kind,
    export_site,
    git_publish,
    public_hand,
    select_hands,
    short_message,
    verdict,
)
from arena.history import read_hands
from arena.intake import submit
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
BOTS = {
    "caller": "class B(PokerBot):\n    def act(self, s):\n"
    "        return Action.call()\n",
    "folder": "class B(PokerBot):\n    def act(self, s):\n"
    "        return Action.fold()\n",
    "raiser": "class B(PokerBot):\n    def act(self, s):\n"
    "        if s.can_raise or s.can_bet:\n"
    "            return Action.raise_to(s.min_raise_to)\n"
    "        return Action.call()\n",
    # Fails validation: the message is a traceback quoting its own source.
    "broken": "class B(PokerBot):\n    def act(self, s):\n"
    "        raise RuntimeError('SECRET-SOURCE-MARKER')\n",
}


def strict_loads(text: str):
    """json.loads that rejects Infinity and NaN, like a browser does."""

    def refuse(name):
        raise ValueError(f"not valid JSON: {name}")

    return json.loads(text, parse_constant=refuse)


def load(path: Path):
    return strict_loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def competition(tmp_path_factory):
    base = tmp_path_factory.mktemp("export")
    store = Store(base / "arena_data")
    for name, body in BOTS.items():
        folder = base / "src" / name
        folder.mkdir(parents=True)
        (folder / "bot.py").write_text(HEADER + body)
        submit(store, name, str(folder))
    settings = Settings(deals=10, workers=2, time_cap_seconds=120)
    enqueue_ladder(store, deals=10)
    run_pending(store, settings, kinds=("ladder",))
    freeze_id, _ = freeze_submissions(store)
    enqueue_final(store, freeze_id, deals=12)
    run_pending(store, settings, kinds=("final",))
    return store


def run_export(competition, tmp_path, **options):
    out = tmp_path / "site"
    summary = export_site(
        competition.root, out, ExportOptions(title="Test Cup", **options)
    )
    return out, summary


# -- data files --------------------------------------------------------


def test_export_writes_strictly_valid_json_for_every_data_file(
    competition, tmp_path
):
    out, summary = run_export(competition, tmp_path)

    names = {p.name for p in (out / "data").glob("*.json")}
    assert names == {
        "manifest.json",
        "teams.json",
        "leaderboard-ladder.json",
        "leaderboard-final.json",
        "pairings-ladder.json",
        "pairings-final.json",
    }
    for path in (out / "data").rglob("*.json"):
        load(path)  # raises on Infinity / NaN
    assert summary.teams == 3
    assert summary.ladder_pairings == summary.final_pairings == 3
    assert summary.final_available


def test_manifest_describes_the_event_and_the_replay_policy(
    competition, tmp_path
):
    out, _ = run_export(competition, tmp_path, submit_text="Push to git.")

    manifest = load(out / "data" / "manifest.json")
    assert manifest["title"] == "Test Cup"
    assert manifest["submit_text"] == "Push to git."
    assert manifest["kinds"] == ["ladder", "final"]
    assert manifest["final_available"] is True
    assert manifest["replays"] == {
        "policy": "final",
        "reveal": "showdown",
        "max_per_pairing": 60,
    }


def test_pairings_report_a_verdict_and_never_expose_fault_text(
    competition, tmp_path
):
    out, _ = run_export(competition, tmp_path)

    pairings = load(out / "data" / "pairings-ladder.json")
    assert len(pairings) == 3
    by_pair = {frozenset((p["a"], p["b"])): p for p in pairings}
    folder_pair = by_pair[frozenset(("caller", "folder"))]
    # A folder loses exactly 0.75 bb/hand, so the verdict is clear.
    winner = "caller"
    expected = "a" if folder_pair["a"] == winner else "b"
    assert folder_pair["verdict"] == expected
    for pairing in pairings:
        assert set(pairing) >= {"id", "a", "b", "mean_bb", "ci95_bb"}
        assert "fault_log_a" not in pairing and "fault_log_b" not in pairing
        assert pairing["disabled_a"] is None and pairing["disabled_b"] is None


def test_teams_list_every_version_and_hide_traceback_source(
    competition, tmp_path
):
    out, _ = run_export(competition, tmp_path)

    text = (out / "data" / "teams.json").read_text(encoding="utf-8")
    teams = {t["team"]: t for t in strict_loads(text)["teams"]}
    assert set(teams) == {"broken", "caller", "folder", "raiser"}
    assert teams["broken"]["current"] is None
    assert teams["broken"]["versions"][0]["status"] == "invalid"
    assert teams["caller"]["current"] == teams["caller"]["frozen"]
    # The traceback quotes the team's own source line; only the exception
    # itself may be published.
    assert "SECRET-SOURCE-MARKER" in teams["broken"]["versions"][0]["message"]
    assert "raise RuntimeError" not in text
    assert "Traceback" not in text
    # ... and the organiser's file system layout stays out of the page too.
    messages = [v["message"] for t in teams.values() for v in t["versions"]]
    assert not any("\\" in m or "Users" in m for m in messages)
    assert "DISABLED" not in text


def test_exporting_before_any_freeze_has_no_final_files(tmp_path):
    store = Store(tmp_path / "arena_data")
    folder = tmp_path / "src" / "caller"
    folder.mkdir(parents=True)
    (folder / "bot.py").write_text(HEADER + BOTS["caller"])
    submit(store, "caller", str(folder))

    summary = export_site(store.root, tmp_path / "site", ExportOptions())

    assert not summary.final_available
    assert not (tmp_path / "site/data/leaderboard-final.json").exists()
    manifest = load(tmp_path / "site/data/manifest.json")
    assert manifest["kinds"] == ["ladder"]


# -- replay policy and privacy ----------------------------------------


def replay_files(out: Path):
    return sorted((out / "data" / "replays").glob("*.json"))


def test_default_policy_publishes_replays_for_the_final_only(
    competition, tmp_path
):
    out, summary = run_export(competition, tmp_path)

    assert [p.name.split("-")[0] for p in replay_files(out)] == ["final"] * 3
    ladder = load(out / "data" / "pairings-ladder.json")
    final = load(out / "data" / "pairings-final.json")
    assert all(p["replay"] is None for p in ladder)
    assert all((out / p["replay"]).exists() for p in final)
    assert summary.replay_files == 3


def test_policy_none_publishes_no_replays(competition, tmp_path):
    out, summary = run_export(competition, tmp_path, replays="none")

    assert not (out / "data" / "replays").exists()
    assert summary.replay_files == 0
    pairings = load(out / "data" / "pairings-final.json")
    assert all(p["replay"] is None for p in pairings)


def test_changing_the_policy_adds_and_removes_replay_files(
    competition, tmp_path
):
    out, _ = run_export(competition, tmp_path, replays="final")
    assert len(replay_files(out)) == 3

    export_site(
        competition.root, out, ExportOptions(title="Test Cup", replays="all")
    )
    assert len(replay_files(out)) == 6

    export_site(
        competition.root, out, ExportOptions(title="Test Cup", replays="none")
    )
    assert replay_files(out) == []


def test_showdown_reveal_hides_cards_of_folded_hands_and_all_seeds(
    competition, tmp_path
):
    out, _ = run_export(competition, tmp_path, max_replay_hands=0)

    folded = shown = 0
    for path in replay_files(out):
        replay = load(path)
        assert replay["reveal"] == "showdown"
        for hand in replay["hands"]:
            assert "seed" not in hand
            if hand["end"] == "fold":
                folded += 1
                assert hand["hole"] is None
            else:
                shown += 1
                assert hand["hole"] and len(hand["hole"]) == 2
                assert len(hand["board"]) == 5
    assert folded and shown  # the fixture exercises both cases

    # No shuffle seed of any dealt hand appears anywhere in the replays.
    text = "".join(p.read_text(encoding="utf-8") for p in replay_files(out))
    for row in competition.results("final"):
        for hand in read_hands(competition.root / row["hands_path"]):
            assert str(hand["deal_seed"]) not in text


def test_reveal_all_publishes_every_hole_card_and_the_seeds(
    competition, tmp_path
):
    out, _ = run_export(
        competition, tmp_path, reveal="all", max_replay_hands=0
    )

    for path in replay_files(out):
        for hand in load(path)["hands"]:
            assert hand["hole"] is not None
            assert isinstance(hand["seed"], str)  # JS cannot hold 64-bit ints


def test_replay_cap_keeps_the_biggest_swings(competition, tmp_path):
    out, _ = run_export(competition, tmp_path, max_replay_hands=5)

    for path in replay_files(out):
        replay = load(path)
        assert replay["shown"] == len(replay["hands"]) == 5
        assert replay["selection"] == "swings"
        assert replay["total_hands"] == 24  # 12 deals, both orientations
        order = [hand["n"] for hand in replay["hands"]]
        assert order == sorted(order)


# -- sanitising helpers -----------------------------------------------


def hand_record(**overrides):
    record = {
        "hand_index": 4,
        "deal_seed": 18446744073709551557,
        "seats": ["a", "b"],
        "stacks": [2000, 2000],
        "hole_cards": [["AS", "KS"], ["2D", "7C"]],
        "board": ["2H", "8D", "QS", "6H", "5C"],
        "small_blind": 10,
        "big_blind": 20,
        "dealer_seat": 0,
        "actions": [
            {
                "seat": 0,
                "action": "post_small_blind",
                "amount": 10,
                "street": "preflop",
                "fault": None,
            },
            {
                "seat": 1,
                "action": "post_big_blind",
                "amount": 20,
                "street": "preflop",
                "fault": None,
            },
            {
                "seat": 0,
                "action": "call",
                "amount": 10,
                "street": "preflop",
                "fault": None,
            },
            {
                "seat": 1,
                "action": "check",
                "amount": None,
                "street": "preflop",
                "fault": "AgentFault: Traceback ... SECRET-FAULT-TEXT",
            },
            {
                "seat": 1,
                "action": "fold",
                "amount": None,
                "street": "flop",
                "fault": None,
            },
        ],
        "ended_by": "fold",
        "results": [
            {"player_id": "seat0", "hand": "Won by Fold", "winnings": 40},
            {"player_id": "seat1", "hand": "Folded", "winnings": 0},
        ],
        "net": [20, -20],
        "faults": 1,
    }
    record.update(overrides)
    return record


def test_fault_text_is_reduced_to_a_flag():
    hand = public_hand(hand_record(), "showdown")

    assert "SECRET-FAULT-TEXT" not in json.dumps(hand)
    assert [a[4] for a in hand["actions"]] == [0, 0, 0, 1, 0]


def test_board_is_cut_to_the_streets_that_were_dealt():
    # Folded on the flop: three cards were dealt, the rest never were.
    assert public_hand(hand_record(), "showdown")["board"] == [
        "2H",
        "8D",
        "QS",
    ]
    preflop = hand_record(
        actions=hand_record()["actions"][:3]
        + [
            {
                "seat": 1,
                "action": "fold",
                "amount": None,
                "street": "preflop",
                "fault": None,
            }
        ]
    )
    assert public_hand(preflop, "showdown")["board"] == []
    showdown = hand_record(ended_by="showdown")
    assert len(public_hand(showdown, "showdown")["board"]) == 5


def test_hole_cards_follow_the_reveal_mode():
    assert public_hand(hand_record(), "showdown")["hole"] is None
    assert public_hand(hand_record(), "all")["hole"][0] == ["AS", "KS"]
    shown = public_hand(hand_record(ended_by="showdown"), "showdown")
    assert shown["hole"] is not None
    assert "seed" not in public_hand(hand_record(), "showdown")
    assert public_hand(hand_record(), "all")["seed"] == "18446744073709551557"


def test_select_hands_prefers_big_swings_then_showdowns():
    def hand(index, swing, ended="fold"):
        return {
            "hand_index": index,
            "net": [swing, -swing],
            "ended_by": ended,
        }

    hands = [
        hand(0, 20),
        hand(1, 20, "showdown"),
        hand(2, 500),
        hand(3, 20),
        hand(4, 300),
    ]

    chosen = select_hands(hands, 3)

    assert [h["hand_index"] for h in chosen] == [1, 2, 4]  # play order
    assert select_hands(hands, 0) == hands
    assert select_hands(hands, 10) == hands


def test_short_message_keeps_only_the_exception_line():
    # The shape of a real stored message: a wrapped traceback plus the
    # harness note, with absolute paths and the team's own source line.
    stored = (
        "AgentFault: Traceback (most recent call last):\n"
        '  File "C:\\Users\\organiser\\arena\\bothost.py", line 112, in main\n'
        "    reply = act_on_message(bot, parser, message)\n"
        '  File "/home/organiser/arena_data/x/bot.py", line 5, in act\n'
        "    raise RuntimeError('SECRET')\n"
        "RuntimeError: bad bot\n"
        "; DISABLED: 1 faults"
    )

    assert short_message(stored) == "RuntimeError: bad bot"
    assert short_message(None) == ""
    assert short_message("") == ""
    assert len(short_message("x" * 500)) <= 140


def test_short_message_blanks_file_paths_inside_the_exception_text():
    windows = "FileNotFoundError: C:\\Users\\me\\data\\model.bin missing"
    posix = "FileNotFoundError: /home/me/data/model.bin missing"

    assert short_message(windows) == "FileNotFoundError: <path> missing"
    assert short_message(posix) == "FileNotFoundError: <path> missing"
    # Ordinary text with a slash is left alone.
    assert short_message("ValueError: bad a/b ratio") == (
        "ValueError: bad a/b ratio"
    )


@pytest.mark.parametrize(
    "message",
    [
        "fatal: repository 'https://github.com/alpha/bot/' not found",
        "fatal: unable to access 'https://github.com/a/b.git/': Could not "
        "resolve host: github.com",
        "error: pathspec 'ssh://git@host/x/y' did not match",
    ],
)
def test_web_addresses_in_a_message_are_not_mistaken_for_file_paths(message):
    # "https://host/a/b" contains "s:/" and "/a/b"; an earlier pattern turned
    # it into "http<path>" and made git errors useless.
    assert short_message(message) == message


def test_a_path_next_to_a_url_is_still_blanked():
    text = (
        "error: cannot write C:\\Users\\me\\x.txt for https://github.com/a/b"
    )

    assert short_message(text) == (
        "error: cannot write <path> for https://github.com/a/b"
    )


def test_disabled_reasons_become_categories():
    assert disabled_kind(None) is None
    assert disabled_kind("time budget exceeded (1.2s > 1.0s)") == "time"
    assert disabled_kind("too many faults (20)") == "faults"
    assert disabled_kind("bot failed to start") == "start"
    assert disabled_kind("something odd") == "other"


def test_verdict_needs_the_interval_to_clear_zero():
    assert verdict(0.5, 0.2) == "a"
    assert verdict(-0.5, 0.2) == "b"
    assert verdict(0.1, 0.2) == "tie"
    assert verdict(None, None) == "tie"
    assert verdict(0.5, None) == "tie"


# -- running it repeatedly --------------------------------------------


def test_a_second_export_of_unchanged_results_changes_nothing(
    competition, tmp_path
):
    out, first = run_export(competition, tmp_path)
    manifest = (out / "data" / "manifest.json").read_text(encoding="utf-8")
    stamp = {p: p.stat().st_mtime_ns for p in (out / "data").rglob("*.json")}

    second = export_site(
        competition.root, out, ExportOptions(title="Test Cup")
    )

    assert first.changed and not second.changed
    assert second.generated_at == first.generated_at
    assert (out / "data" / "manifest.json").read_text(
        encoding="utf-8"
    ) == manifest
    assert stamp == {
        p: p.stat().st_mtime_ns for p in (out / "data").rglob("*.json")
    }


def test_changing_the_title_counts_as_a_change(competition, tmp_path):
    out, _ = run_export(competition, tmp_path)

    again = export_site(competition.root, out, ExportOptions(title="Other"))

    assert again.changed
    assert load(out / "data" / "manifest.json")["title"] == "Other"


def test_export_refuses_bad_options_and_missing_data(tmp_path):
    with pytest.raises(ExportError, match="no competition data"):
        export_site(tmp_path / "nothing", tmp_path / "site", ExportOptions())
    with pytest.raises(ExportError, match="replays"):
        ExportOptions(replays="sometimes").validate()
    with pytest.raises(ExportError, match="reveal"):
        ExportOptions(reveal="maybe").validate()
    with pytest.raises(ExportError, match="negative"):
        ExportOptions(max_replay_hands=-1).validate()


# -- publishing --------------------------------------------------------


def git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_git_publish_commits_and_pushes_only_real_changes(
    competition, tmp_path
):
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    git("init", "--bare", "-q", str(remote), cwd=tmp_path)
    git("clone", "-q", str(remote), str(work), cwd=tmp_path)
    git("config", "user.email", "t@example.com", cwd=work)
    git("config", "user.name", "Test", cwd=work)
    git("commit", "--allow-empty", "-q", "-m", "init", cwd=work)
    git("push", "-q", "-u", "origin", "HEAD", cwd=work)

    export_site(competition.root, work, ExportOptions(title="Test Cup"))
    assert git_publish(work, "Update results") is True
    assert git_publish(work, "Update results") is False  # nothing new

    shown = git(
        "--git-dir",
        str(remote),
        "show",
        "HEAD:data/manifest.json",
        cwd=tmp_path,
    )
    assert strict_loads(shown)["title"] == "Test Cup"


def test_git_publish_reports_a_folder_that_is_not_a_repository(tmp_path):
    folder = tmp_path / "plain"
    folder.mkdir()

    with pytest.raises(ExportError):
        git_publish(folder, "x")


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_a_failed_push_is_retried_on_the_next_pass(competition, tmp_path):
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    git("init", "--bare", "-q", str(remote), cwd=tmp_path)
    git("clone", "-q", str(remote), str(work), cwd=tmp_path)
    git("config", "user.email", "t@example.com", cwd=work)
    git("config", "user.name", "Test", cwd=work)
    git("commit", "--allow-empty", "-q", "-m", "init", cwd=work)
    git("push", "-q", "-u", "origin", "HEAD", cwd=work)
    export_site(competition.root, work, ExportOptions())

    # The network "drops": the remote disappears mid-event.
    moved = tmp_path / "away.git"
    remote.rename(moved)
    with pytest.raises(ExportError):
        git_publish(work, "Update results")
    moved.rename(remote)

    # The commit made during the outage is pushed on the next pass.
    assert git_publish(work, "Update results") is True
    shown = git(
        "--git-dir",
        str(remote),
        "show",
        "HEAD:data/manifest.json",
        cwd=tmp_path,
    )
    assert strict_loads(shown)["schema"] == 1
    assert git_publish(work, "Update results") is False


def test_a_team_whose_repository_cannot_be_fetched_is_listed_with_the_reason(
    tmp_path,
):
    store = Store(tmp_path / "arena_data")
    store.set_sync_status(
        "ghost",
        "unreachable",
        "git clone failed: fatal: repository "
        "'https://github.com/ghost/bot/' not found",
    )
    store.set_sync_status(
        "leaky", "rejected", "failed to read C:/Users/organiser/x/bot.py"
    )

    export_site(store.root, tmp_path / "site", ExportOptions())

    text = (tmp_path / "site/data/teams.json").read_text(encoding="utf-8")
    teams = {t["team"]: t for t in strict_loads(text)["teams"]}
    assert teams["ghost"]["versions"] == []
    assert teams["ghost"]["current"] is None
    assert teams["ghost"]["sync"]["status"] == "unreachable"
    # The address is kept (it is the team's own, public repository) ...
    assert "https://github.com/ghost/bot/" in teams["ghost"]["sync"]["message"]
    # ... but the organiser's file paths never reach the page.
    assert "Users" not in text and "organiser" not in text


def test_a_team_without_any_sync_has_no_sync_entry(competition, tmp_path):
    out, _ = run_export(competition, tmp_path)

    teams = load(out / "data" / "teams.json")["teams"]

    assert all(team["sync"] is None for team in teams)


# -- the how-to-submit guide ------------------------------------------


def test_the_guide_is_published_as_markdown_and_announced_in_the_manifest(
    tmp_path,
):
    store = Store(tmp_path / "arena_data")

    export_site(store.root, tmp_path / "site", ExportOptions(guide="# Hi\n"))

    assert (tmp_path / "site/data/submitting.md").read_text(
        encoding="utf-8"
    ) == "# Hi\n"
    assert load(tmp_path / "site/data/manifest.json")["has_guide"] is True


def test_without_a_guide_there_is_no_file_and_the_manifest_says_so(tmp_path):
    store = Store(tmp_path / "arena_data")
    out = tmp_path / "site"
    export_site(store.root, out, ExportOptions(guide="# Hi\n"))

    again = export_site(store.root, out, ExportOptions())

    assert again.changed  # removing the guide is a change
    assert not (out / "data" / "submitting.md").exists()
    assert load(out / "data" / "manifest.json")["has_guide"] is False


def test_editing_the_guide_counts_as_a_change_and_is_otherwise_stable(
    tmp_path,
):
    store = Store(tmp_path / "arena_data")
    out = tmp_path / "site"
    first = export_site(store.root, out, ExportOptions(guide="one"))

    same = export_site(store.root, out, ExportOptions(guide="one"))
    edited = export_site(store.root, out, ExportOptions(guide="two"))

    assert first.changed and not same.changed and edited.changed
    assert (out / "data" / "submitting.md").read_text() == "two"


def test_a_repeated_sync_check_does_not_change_the_published_data(tmp_path):
    """Regression: a sync pass runs every minute; if its time was published,
    every export changed the site data and a git host deployed it every
    minute although nothing had happened."""
    store = Store(tmp_path / "arena_data")
    out = tmp_path / "site"
    store.set_sync_status("alpha", "unreachable", "fatal: not found")
    first = export_site(store.root, out, ExportOptions())
    before = (out / "data" / "teams.json").read_text(encoding="utf-8")

    time.sleep(0.05)
    store.set_sync_status("alpha", "unreachable", "fatal: not found")  # again
    second = export_site(store.root, out, ExportOptions())

    assert first.changed and not second.changed
    assert (out / "data" / "teams.json").read_text(encoding="utf-8") == before
    # ... but a real change (the repository is now fixed) does get published.
    store.set_sync_status("alpha", "valid", "fine")
    third = export_site(store.root, out, ExportOptions())
    assert third.changed


def test_the_status_time_moves_only_when_the_outcome_changes(tmp_path):
    store = Store(tmp_path / "arena_data")
    store.set_sync_status("alpha", "rejected", "no bot.py")
    first = store.sync_statuses()["alpha"]

    time.sleep(0.05)
    store.set_sync_status("alpha", "rejected", "no bot.py")
    same = store.sync_statuses()["alpha"]
    time.sleep(0.05)
    store.set_sync_status("alpha", "valid", "ok")
    changed = store.sync_statuses()["alpha"]

    assert same["at"] == first["at"]  # unchanged outcome: same time
    assert same["checked_at"] > first["checked_at"]  # but it was re-checked
    assert changed["at"] > first["at"]  # a new outcome: new time
