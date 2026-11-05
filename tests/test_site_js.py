"""Runs the site's JavaScript unit tests (tests/site_js) under Node.

The pure modules of the static site (formatting, chart maths, the replay
builder) are tested against real hand histories. Node ships on CI runners;
on a machine without it the test is skipped, not failed.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
JS_TESTS = sorted((REPO / "tests" / "site_js").glob("*.test.mjs"))


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_site_javascript_unit_tests_pass():
    assert JS_TESTS, "no JavaScript tests found"

    done = subprocess.run(
        ["node", "--test", *[str(path) for path in JS_TESTS]],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert done.returncode == 0, done.stdout + done.stderr
