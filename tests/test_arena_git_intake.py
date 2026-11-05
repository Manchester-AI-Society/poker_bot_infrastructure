"""Submitting from git: unattended, and never running a team's input."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest

from arena.intake import (
    SubmissionError,
    _git_environment,
    is_git_url,
    submit,
)
from arena.store import Store

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git not installed"
)

HEADER = (
    "from player_sdk.bot_interface import PokerBot\n"
    "from player_sdk.models import Action\n"
)
CALLER = HEADER + (
    "class B(PokerBot):\n    def act(self, s):\n        return Action.call()\n"
)
FOLDER = HEADER + (
    "class B(PokerBot):\n    def act(self, s):\n        return Action.fold()\n"
)


def git(*args, cwd):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def make_repo(path: Path, files: dict[str, str]) -> str:
    """A local git repository; returns its file:// URL."""
    path.mkdir(parents=True)
    git("init", "-q", "-b", "main", cwd=path)
    for name, text in files.items():
        (path / name).write_text(text)
    git("add", "-A", cwd=path)
    git("commit", "-q", "-m", "bot", cwd=path)
    return path.as_uri()


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "arena_data")


def test_a_bot_is_cloned_validated_and_made_current(store, tmp_path):
    url = make_repo(tmp_path / "alpha", {"bot.py": CALLER})

    result = submit(store, "alpha", url)

    assert result.status == "valid"
    assert store.current_hash("alpha") == result.digest
    stored = store.root / "versions" / "alpha" / result.digest
    assert (stored / "bot.py").exists()
    assert not (stored / ".git").exists()  # history is not copied


def test_resubmitting_an_unchanged_repository_changes_nothing(store, tmp_path):
    url = make_repo(tmp_path / "alpha", {"bot.py": CALLER})
    first = submit(store, "alpha", url)

    again = submit(store, "alpha", url)

    assert again.status == "unchanged" and again.digest == first.digest


def test_a_new_commit_becomes_a_new_version(store, tmp_path):
    repo = tmp_path / "alpha"
    url = make_repo(repo, {"bot.py": CALLER})
    first = submit(store, "alpha", url)
    (repo / "bot.py").write_text(FOLDER)
    git("commit", "-q", "-am", "change", cwd=repo)

    second = submit(store, "alpha", url)

    assert second.status == "valid" and second.digest != first.digest
    assert store.current_hash("alpha") == second.digest


def test_a_chosen_branch_is_the_one_that_is_submitted(store, tmp_path):
    repo = tmp_path / "alpha"
    url = make_repo(repo, {"bot.py": FOLDER})
    git("checkout", "-q", "-b", "dev", cwd=repo)
    (repo / "bot.py").write_text(CALLER)
    git("commit", "-q", "-am", "dev bot", cwd=repo)
    git("checkout", "-q", "main", cwd=repo)

    on_main = submit(store, "alpha", url)
    on_dev = submit(store, "beta", url, branch="dev")

    assert on_main.digest != on_dev.digest
    assert (
        store.root / "versions" / "beta" / on_dev.digest / "bot.py"
    ).read_text() == CALLER


def test_a_missing_branch_is_a_clear_rejection(store, tmp_path):
    url = make_repo(tmp_path / "alpha", {"bot.py": CALLER})

    with pytest.raises(SubmissionError, match="git clone failed"):
        submit(store, "alpha", url, branch="no-such-branch")


def test_a_repository_without_bot_py_is_rejected_clearly(store, tmp_path):
    url = make_repo(tmp_path / "alpha", {"README.md": "no bot here"})

    with pytest.raises(SubmissionError, match="bot.py"):
        submit(store, "alpha", url)


# -- safety ------------------------------------------------------------


def test_a_source_that_looks_like_a_git_option_is_never_passed_to_git(
    store, tmp_path, monkeypatch
):
    # Ends in ".git", so is_git_url() accepts it; without "--" git would run
    # the --upload-pack program.
    marker = tmp_path / "pwned"
    evil = f"--upload-pack=touch {marker}.git"
    monkeypatch.chdir(tmp_path)

    assert is_git_url(evil)
    with pytest.raises(SubmissionError, match="cannot start with"):
        submit(store, "alpha", evil)

    assert not list(tmp_path.glob("pwned*"))


@pytest.mark.parametrize("branch", ["--upload-pack=x", "-b", "a b", "x;y", ""])
def test_a_branch_name_cannot_be_an_option_or_contain_junk(
    store, tmp_path, branch
):
    url = make_repo(tmp_path / "alpha", {"bot.py": CALLER})

    with pytest.raises(SubmissionError, match="branch"):
        submit(store, "alpha", url, branch=branch)


def test_git_is_told_never_to_ask_for_a_password():
    # A private repository would otherwise open a credential pop-up on
    # Windows and stall a loop that clones many repositories.
    environment = _git_environment()

    assert environment["GIT_TERMINAL_PROMPT"] == "0"
    assert environment["GCM_INTERACTIVE"] == "never"


def test_an_unreachable_repository_fails_fast_instead_of_hanging(store):
    started = time.monotonic()

    with pytest.raises(SubmissionError, match="git clone failed"):
        submit(store, "alpha", "https://127.0.0.1:9/nobody/nothing.git")

    assert time.monotonic() - started < 30


def test_a_slow_clone_is_cut_off(store, tmp_path):
    url = make_repo(tmp_path / "alpha", {"bot.py": CALLER})

    with pytest.raises(SubmissionError, match="git clone failed"):
        submit(store, "alpha", url, clone_timeout=0.001)
