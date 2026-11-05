"""Pulling every team's bot from its own repository."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest

from arena.cli import main
from arena.store import Store
from arena.sync import (
    Reporter,
    TeamsFile,
    TeamsFileError,
    load_teams,
    parse_teams,
    start_background,
    sync_teams,
)

needs_git = pytest.mark.skipif(
    shutil.which("git") is None, reason="git not installed"
)

HEADER = (
    "from player_sdk.bot_interface import PokerBot\n"
    "from player_sdk.models import Action\n"
)


def bot(action: str) -> str:
    return HEADER + (
        "class B(PokerBot):\n    def act(self, s):\n"
        f"        return Action.{action}()\n"
    )


CALLER, FOLDER = bot("call"), bot("fold")
BROKEN = HEADER + (
    "class B(PokerBot):\n    def act(self, s):\n"
    "        raise RuntimeError('boom')\n"
)
FILE = ("file://",)


# -- the teams file ----------------------------------------------------


def test_a_teams_file_is_parsed_with_comments_branches_and_blank_lines():
    text = """
# team   repository                          branch
alpha    https://github.com/a/bot
Beta,    https://github.com/b/bot            dev   # a trailing comment

gamma https://gitlab.com/g/bot.git
"""

    sources = parse_teams(text)

    assert [(s.team, s.url, s.branch) for s in sources] == [
        ("alpha", "https://github.com/a/bot", None),
        ("beta", "https://github.com/b/bot", "dev"),
        ("gamma", "https://gitlab.com/g/bot.git", None),
    ]
    assert [s.line for s in sources] == [3, 4, 6]


def test_an_empty_teams_file_is_fine():
    assert parse_teams("# nothing yet\n\n") == []


def test_every_problem_is_reported_with_its_line_number():
    text = chr(10).join(
        [
            "alpha https://github.com/a/bot",  # 1: fine
            "alpha https://github.com/other/bot",  # 2: duplicate team
            "Bad_Team! https://github.com/b/bot",  # 3: invalid name
            "gamma http://github.com/g/bot",  # 4: not https
            "delta https://user:secret@github.com/d/bot",  # 5: a login
            "eps https://github.com/eps/bot",  # 6: fine
            "eta https://github.com/e/bot nobranch extra",  # 7: columns
            "theta https://github.com/t/bot -x",  # 8: bad branch
            "iota",  # 9: too few columns
        ]
    )

    with pytest.raises(TeamsFileError) as raised:
        parse_teams(text)

    message = str(raised.value)
    for line in (2, 3, 4, 5, 7, 8, 9):
        assert f"line {line}:" in message
    for line in (1, 6):
        assert f"line {line}:" not in message
    assert "secret" not in message  # a pasted token is never echoed back


def test_the_same_repository_cannot_belong_to_two_teams():
    text = (
        "alpha https://github.com/x/bot\nbeta  https://GitHub.com/x/Bot.git/\n"
    )

    with pytest.raises(TeamsFileError, match="already used by 'alpha'"):
        parse_teams(text)


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:x/bot.git",
        "ssh://git@github.com/x/bot",
        "file:///etc",
        "ext::sh -c touch% /tmp/x",
        "https://",
        "--upload-pack=x",
        "https://github.com/" + "a" * 400,
    ],
)
def test_only_plain_https_repositories_are_accepted(url):
    with pytest.raises(TeamsFileError):
        parse_teams(f"alpha {url}")


def test_a_byte_order_mark_from_notepad_is_tolerated(tmp_path):
    path = tmp_path / "teams.txt"
    path.write_bytes(b"\xef\xbb\xbfalpha https://github.com/a/bot\n")

    assert [s.team for s in load_teams(path)] == ["alpha"]


def test_a_missing_teams_file_says_so(tmp_path):
    with pytest.raises(TeamsFileError, match="cannot read"):
        load_teams(tmp_path / "nope.txt")


# -- fetching real repositories ---------------------------------------


def git(*args, cwd):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def make_repo(path: Path, text: str | None) -> str:
    path.mkdir(parents=True)
    git("init", "-q", "-b", "main", cwd=path)
    (path / "bot.py" if text else path / "README.md").write_text(
        text or "no bot"
    )
    git("add", "-A", cwd=path)
    git("commit", "-q", "-m", "x", cwd=path)
    return path.as_uri()


def push(path: Path, text: str) -> None:
    (path / "bot.py").write_text(text)
    git("commit", "-q", "-am", "update", cwd=path)


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "arena_data")


def teams_for(**repos: str):
    text = "\n".join(f"{team} {url}" for team, url in repos.items())
    return parse_teams(text, allowed=FILE)


@needs_git
def test_every_team_is_pulled_and_the_outcome_is_remembered(store, tmp_path):
    sources = teams_for(
        alpha=make_repo(tmp_path / "a", CALLER),
        beta=make_repo(tmp_path / "b", FOLDER),
    )

    results = sync_teams(store, sources)

    assert [r.status for r in results] == ["valid", "valid"]
    assert {v.team for v in store.current_versions()} == {"alpha", "beta"}
    assert store.sync_statuses()["alpha"]["status"] == "valid"


@needs_git
def test_a_second_pass_changes_nothing_and_a_push_becomes_a_new_version(
    store, tmp_path
):
    repo = tmp_path / "a"
    sources = teams_for(alpha=make_repo(repo, CALLER))
    first = sync_teams(store, sources)[0]

    again = sync_teams(store, sources)[0]
    push(repo, FOLDER)
    updated = sync_teams(store, sources)[0]

    assert again.status == "unchanged" and again.digest == first.digest
    assert updated.status == "valid" and updated.digest != first.digest
    assert store.current_hash("alpha") == updated.digest


@needs_git
def test_a_broken_push_never_replaces_the_working_bot(store, tmp_path):
    repo = tmp_path / "a"
    sources = teams_for(alpha=make_repo(repo, CALLER))
    good = sync_teams(store, sources)[0]
    push(repo, BROKEN)

    broken = sync_teams(store, sources)[0]
    again = sync_teams(store, sources)[0]  # the same bad commit, not re-run

    assert broken.status == "invalid" and "boom" in broken.message
    assert again.status == "invalid"
    assert store.current_hash("alpha") == good.digest
    assert store.sync_statuses()["alpha"]["status"] == "invalid"


@needs_git
def test_each_kind_of_failure_is_named_and_does_not_stop_the_others(
    store, tmp_path
):
    sources = teams_for(
        good=make_repo(tmp_path / "g", CALLER),
        nobot=make_repo(tmp_path / "n", None),
        missing=(tmp_path / "does-not-exist").as_uri(),
    )

    results = {r.team: r for r in sync_teams(store, sources)}

    assert results["good"].status == "valid"
    assert results["nobot"].status == "rejected"
    assert "bot.py" in results["nobot"].message
    assert results["missing"].status == "unreachable"
    assert store.current_hash("good") is not None


@needs_git
def test_copying_another_teams_code_is_rejected(store, tmp_path):
    sources = teams_for(
        alpha=make_repo(tmp_path / "a", CALLER),
        copycat=make_repo(tmp_path / "c", CALLER),
    )

    results = {r.team: r for r in sync_teams(store, sources)}

    assert results["alpha"].status == "valid"
    assert results["copycat"].status == "rejected"
    assert "already submitted by 'alpha'" in results["copycat"].message


def test_an_unexpected_error_for_one_team_is_contained(store, monkeypatch):
    import arena.sync as module

    def explode(*args, **kwargs):
        raise MemoryError("out of memory")

    monkeypatch.setattr(module, "submit", explode)

    (result,) = sync_teams(
        store, parse_teams("alpha https://github.com/a/bot")
    )

    assert result.status == "error" and "MemoryError" in result.message


# -- the loop and the file --------------------------------------------


def test_the_reporter_prints_a_change_once_not_every_pass():
    from arena.sync import SyncResult

    reporter = Reporter()
    ok = SyncResult("alpha", "valid", "abc123", "fine")
    same = SyncResult("alpha", "unchanged", "abc123", "identical")
    bad = SyncResult(
        "beta", "unreachable", "", "git clone failed: x\nfatal: nope"
    )

    first = reporter.lines([ok, bad])
    second = reporter.lines([same, bad])
    third = reporter.lines([same, SyncResult("beta", "valid", "d1", "ok")])

    assert len(first) == 2 and "unreachable" in first[1]
    assert "fatal: nope" in first[1]  # the useful last line, not the first
    assert second == []  # nothing changed
    assert len(third) == 1 and "beta: valid" in third[0]


def test_a_half_written_edit_keeps_the_previous_list_and_says_so_once(
    tmp_path,
):
    path = tmp_path / "teams.txt"
    path.write_text("alpha https://github.com/a/bot\n")
    teams = TeamsFile(path)
    said: list[str] = []
    assert [s.team for s in teams.current(said.append)] == ["alpha"]

    path.write_text("alpha https://github.com/a/bot\nbeta oops\n")
    assert [s.team for s in teams.current(said.append)] == ["alpha"]
    assert [s.team for s in teams.current(said.append)] == ["alpha"]

    assert len(said) == 1 and "line 2" in said[0]
    path.write_text("alpha https://github.com/a/bot\nbeta https://x.io/b/c\n")
    assert [s.team for s in teams.current(said.append)] == ["alpha", "beta"]


def test_a_teams_file_that_is_bad_from_the_start_raises(tmp_path):
    path = tmp_path / "teams.txt"
    path.write_text("alpha oops\n")

    with pytest.raises(TeamsFileError):
        TeamsFile(path).current(lambda message: None)


@needs_git
def test_the_background_loop_picks_up_a_new_push_by_itself(
    store, tmp_path, monkeypatch
):
    import arena.sync as module

    repo = tmp_path / "a"
    path = tmp_path / "teams.txt"
    path.write_text(f"alpha {make_repo(repo, CALLER)}\n")
    # file:// is not allowed in a real teams file; allow it for this test
    # only (monkeypatch undoes it, so no other test sees the change).
    monkeypatch.setattr(
        module,
        "load_teams",
        lambda p: parse_teams(Path(p).read_text(), allowed=FILE),
    )
    teams = TeamsFile(path)
    lines: list[str] = []

    stop = start_background(store, teams, 0.2, report=lines.append)
    try:
        deadline = time.monotonic() + 60
        while not store.current_versions() and time.monotonic() < deadline:
            time.sleep(0.1)
        first = store.current_hash("alpha")
        push(repo, FOLDER)
        while (
            store.current_hash("alpha") == first
            and time.monotonic() < deadline
        ):
            time.sleep(0.1)
    finally:
        stop.set()

    assert first is not None
    assert store.current_hash("alpha") not in (None, first)
    assert any("alpha: valid" in line for line in lines)


# -- the command line --------------------------------------------------


def test_sync_command_refuses_a_bad_teams_file_with_exit_code_2(
    tmp_path, capsys
):
    path = tmp_path / "teams.txt"
    path.write_text("alpha file:///some/repo\n")

    code = main(
        ["sync", "--teams", str(path), "--root", str(tmp_path / "d"), "--once"]
    )

    assert code == 2
    assert "line 1" in capsys.readouterr().out


def test_ladder_refuses_a_bad_teams_file_before_doing_anything(
    tmp_path, capsys
):
    path = tmp_path / "teams.txt"
    path.write_text("alpha\n")

    code = main(
        [
            "ladder",
            "--teams",
            str(path),
            "--root",
            str(tmp_path / "d"),
            "--once",
        ]
    )

    assert code == 2
    assert "line 1" in capsys.readouterr().out


def test_sync_once_exits_non_zero_when_a_team_has_a_problem(tmp_path, capsys):
    path = tmp_path / "teams.txt"
    path.write_text("alpha https://127.0.0.1:9/nobody/nothing\n")

    code = main(
        ["sync", "--teams", str(path), "--root", str(tmp_path / "d"), "--once"]
    )

    out = capsys.readouterr().out
    assert code == 1
    assert "alpha: unreachable" in out
    assert "1 of 1 teams have a problem" in out
