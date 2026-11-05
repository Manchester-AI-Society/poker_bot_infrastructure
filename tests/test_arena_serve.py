"""The preview server and the export command line."""

from __future__ import annotations

import json
import threading
import urllib.request

import pytest

from arena.cli import main
from arena.serve import make_server
from arena.store import Store


@pytest.fixture
def served(tmp_path):
    (tmp_path / "js").mkdir()
    (tmp_path / "js" / "app.js").write_text("export const x = 1;")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "m.json").write_text('{"a": 1}')
    (tmp_path / "index.html").write_text("<!doctype html><title>t</title>")
    server = make_server(tmp_path, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def fetch(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.headers, response.read()


def test_javascript_is_served_as_javascript_so_modules_load(served):
    headers, _ = fetch(served + "/js/app.js")

    # Windows can map .js to text/plain, which browsers refuse for modules.
    assert headers["Content-Type"].startswith("text/javascript")


def test_json_and_html_have_the_right_types(served):
    assert fetch(served + "/data/m.json")[0]["Content-Type"].startswith(
        "application/json"
    )
    assert fetch(served + "/")[0]["Content-Type"].startswith("text/html")


def test_nothing_is_cached_so_polling_sees_fresh_data(served):
    headers, body = fetch(served + "/data/m.json")

    assert headers["Cache-Control"] == "no-store"
    assert json.loads(body) == {"a": 1}


def test_export_command_writes_the_site_and_reports_missing_data(
    tmp_path, capsys
):
    # No competition yet: a clear message and a failure exit code.
    code = main(
        [
            "export",
            "--root",
            str(tmp_path / "none"),
            "--out",
            str(tmp_path / "site"),
        ]
    )
    assert code == 1
    assert "no competition data" in capsys.readouterr().out

    Store(tmp_path / "arena_data")  # an (empty) competition
    code = main(
        [
            "export",
            "--root",
            str(tmp_path / "arena_data"),
            "--out",
            str(tmp_path / "site"),
            "--title",
            "Cup",
            "--submit-text",
            "Push to git",
        ]
    )

    assert code == 0
    assert "[export" in capsys.readouterr().out
    manifest = json.loads(
        (tmp_path / "site/data/manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["title"] == "Cup"
    assert manifest["submit_text"] == "Push to git"
