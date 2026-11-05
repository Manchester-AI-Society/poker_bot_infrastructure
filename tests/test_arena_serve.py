"""The preview server and the export command line."""

from __future__ import annotations

import http.client
import json
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pytest

from arena.cli import main
from arena.serve import SiteServer, make_server
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


def test_the_listen_backlog_is_deep_enough_for_a_page_load():
    # Measured on Windows: with the stock backlog of 5, 12 full page loads in
    # Edge took 140 ms each except two that stalled for 29 s and 39 s; with
    # this backlog all 12 took 122-155 ms. Timing varies too much by machine
    # to assert in a test, so the cause is pinned instead.
    assert SiteServer.request_queue_size >= 128


def test_connections_are_kept_alive_so_a_page_load_needs_few_of_them(served):
    host, port = served.removeprefix("http://").split(":")
    connection = http.client.HTTPConnection(host, int(port), timeout=10)
    try:
        connection.request("GET", "/data/m.json")
        first = connection.getresponse()
        first.read()
        connection.request("GET", "/index.html")  # same socket, second request
        second = connection.getresponse()
        second.read()
    finally:
        connection.close()

    assert first.status == second.status == 200
    assert (
        first.version == 11
    )  # HTTP/1.1, not 1.0 with a fresh socket each time


def test_a_burst_of_simultaneous_requests_all_complete(served):
    def get(index):
        with urllib.request.urlopen(
            f"{served}/data/m.json?i={index}", timeout=60
        ) as response:
            return response.read()

    with ThreadPoolExecutor(max_workers=60) as pool:
        bodies = list(pool.map(get, range(60)))

    assert all(json.loads(body) == {"a": 1} for body in bodies)


def test_export_command_publishes_the_repositorys_submitting_guide(tmp_path):
    from arena.cli import DEFAULT_GUIDE

    Store(tmp_path / "arena_data")

    code = main(
        [
            "export",
            "--root",
            str(tmp_path / "arena_data"),
            "--out",
            str(tmp_path / "site"),
        ]
    )

    assert code == 0
    published = (tmp_path / "site/data/submitting.md").read_text(
        encoding="utf-8"
    )
    assert published == DEFAULT_GUIDE.read_text(encoding="utf-8-sig")
    assert "How to submit your bot" in published


def test_export_command_can_leave_the_guide_out_or_use_another(
    tmp_path, capsys
):
    Store(tmp_path / "arena_data")
    root = str(tmp_path / "arena_data")

    main(
        ["export", "--root", root, "--out", str(tmp_path / "a"), "--no-guide"]
    )
    custom = tmp_path / "mine.md"
    custom.write_text("# Our own rules\n", encoding="utf-8")
    main(
        [
            "export",
            "--root",
            root,
            "--out",
            str(tmp_path / "b"),
            "--guide",
            str(custom),
        ]
    )
    code = main(
        [
            "export",
            "--root",
            root,
            "--out",
            str(tmp_path / "c"),
            "--guide",
            str(tmp_path / "missing.md"),
        ]
    )

    assert not (tmp_path / "a/data/submitting.md").exists()
    assert (tmp_path / "b/data/submitting.md").read_text(
        encoding="utf-8"
    ) == "# Our own rules\n"
    assert code == 1
    assert "cannot read the guide" in capsys.readouterr().out
