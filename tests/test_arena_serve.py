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


def test_a_page_load_worth_of_requests_all_complete(served):
    # A browser opens at most 6 connections to one host and loads a few dozen
    # files, so that is what is modelled: 6 at a time, 48 requests. (An earlier
    # version fired 60 simultaneous connections, harsher than any browser; on a
    # busy Windows machine it stalled for minutes and failed intermittently.)
    def get(index):
        with urllib.request.urlopen(
            f"{served}/data/m.json?i={index}", timeout=60
        ) as response:
            return response.read()

    with ThreadPoolExecutor(max_workers=6) as pool:
        bodies = list(pool.map(get, range(48)))

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


# -- the publishing loop must survive anything a pass throws -----------


class StopLoop(Exception):
    pass


def run_export_loop(tmp_path, monkeypatch, behaviours):
    """Runs `export --loop`, each pass doing the next behaviour, then stops.

    A behaviour is an exception to raise or None for a good pass. Sleeping is
    replaced so the test does not wait, and the loop is ended by Ctrl+C.
    """
    import arena.cli as cli

    calls = []
    plan = iter(behaviours)

    def fake_pass(args, options):
        calls.append(1)
        outcome = next(plan, StopLoop())
        if isinstance(outcome, BaseException):
            raise outcome

    def fake_sleep(seconds):
        if len(calls) >= len(behaviours):
            raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_export_once", fake_pass)
    monkeypatch.setattr(cli.time, "sleep", fake_sleep)
    code = main(
        [
            "export",
            "--root",
            str(tmp_path),
            "--out",
            str(tmp_path / "o"),
            "--loop",
            "1",
        ]
    )
    return code, len(calls)


def test_an_unexpected_error_in_a_pass_does_not_end_the_loop(
    tmp_path, monkeypatch, capsys
):
    """Regression: only ExportError was caught, so one BadGzipFile ended the
    publisher and the website froze with nobody noticing."""
    code, passes = run_export_loop(
        tmp_path,
        monkeypatch,
        [None, OSError("Not a gzipped file"), RuntimeError("boom"), None],
    )

    out = capsys.readouterr().out
    assert code == 0 and passes == 4  # it kept going through both failures
    assert "unexpected problem, will retry: OSError" in out
    assert "unexpected problem, will retry: RuntimeError: boom" in out


def test_a_failing_first_pass_in_a_loop_does_not_stop_it(
    tmp_path, monkeypatch, capsys
):
    # For example the network is down when the event starts.
    from arena.export import ExportError

    code, passes = run_export_loop(
        tmp_path, monkeypatch, [ExportError("git push failed"), None]
    )

    assert code == 0 and passes == 2
    assert "problem, will retry: git push failed" in capsys.readouterr().out


def test_a_single_run_still_fails_loudly_on_an_unexpected_error(
    tmp_path, monkeypatch
):
    import arena.cli as cli

    def explode(args, options):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "_export_once", explode)

    with pytest.raises(RuntimeError, match="boom"):
        main(["export", "--root", str(tmp_path), "--out", str(tmp_path / "o")])
