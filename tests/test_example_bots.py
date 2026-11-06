"""The template bot in bots/ must actually work, not just exist."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from arena.duel import PairingConfig, play_pairing
from arena.specs import contestant_from_spec
from arena.validate import smoke_test

REPO = Path(__file__).resolve().parents[1]
BOTS = REPO / "bots"
EXAMPLES = sorted(
    folder.name for folder in BOTS.iterdir() if (folder / "bot.py").is_file()
)


def load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"example_{name}", BOTS / name / "bot.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_template_is_there():
    assert "starter" in EXAMPLES


@pytest.mark.parametrize("name", EXAMPLES)
def test_every_example_loads_and_plays_legally(name, tmp_path):
    report = smoke_test(BOTS / name, deals=10, log_dir=tmp_path)

    assert report.ok, report.message


@pytest.mark.parametrize("name", EXAMPLES)
def test_every_example_has_a_docstring_saying_how_to_try_it(name):
    text = (BOTS / name / "bot.py").read_text(encoding="utf-8")

    assert text.lstrip().startswith('"""')
    assert "python -m arena match" in text


@pytest.mark.parametrize("name", EXAMPLES)
def test_every_example_beats_a_random_player(name):
    config = PairingConfig(deals=100, seed=5, think_budget_per_deal=2.0)

    result = play_pairing(
        contestant_from_spec(str(BOTS / name)),
        contestant_from_spec("random"),
        config,
    )

    assert result.status == "complete"
    assert result.faults_a == 0
    assert result.mean_bb > 0


@pytest.mark.parametrize("name", EXAMPLES)
def test_examples_are_self_contained(name):
    # A team's folder is all that gets copied, so a bot may not import a
    # sibling bot or the repo's own game code.
    text = (BOTS / name / "bot.py").read_text(encoding="utf-8")

    for line in text.splitlines():
        if line.startswith(("import ", "from ")):
            assert not line.startswith(
                ("from bots", "import bots", "from game")
            ), line
            assert "arena" not in line, line
