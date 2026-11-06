"""Team names registered on the website, and checked against submissions."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from arena.cli import main
from arena.export import ExportError, ExportOptions, export_site
from arena.roster import (
    MAX_NAMES,
    REGISTER_FORM,
    RosterError,
    load_registered,
    parse_names,
    roster,
)
from arena.store import Store
from arena.tournament import draw, ensure_tournament

SHEET = (
    "Timestamp,Team name\n"
    "2026/11/07 9:01:02,fox\n"
    "2026/11/07 9:02:10,  Owl  \n"
    "2026/11/07 9:03:44,fox\n"
    "2026/11/07 9:05:00,not a valid name!\n"
    "2026/11/07 9:06:00,<script>x</script>\n"
    "2026/11/07 9:07:00,\n"
    "2026/11/07 9:08:00,bear-2\n"
)

FORM = (
    "https://docs.google.com/forms/d/e/1FAIpQLSdEXAMPLE_id-1/viewform"
    "?usp=pp_url&entry.123456789="
)
SHEET_URL = "https://docs.google.com/x/pub?output=csv"

# -- reading the sheet -------------------------------------------------------


def test_names_are_cleaned_checked_and_deduplicated():
    assert parse_names(SHEET) == ["fox", "owl", "bear-2"]


def test_the_team_column_is_found_by_its_header_or_by_position():
    assert parse_names("Email,Your team,When\na@b.c,fox,1\n") == ["fox"]
    # No header mentions "team": the second column (after the timestamp).
    assert parse_names("Timestamp,Name\n1,fox\n") == ["fox"]
    assert parse_names("Name\nfox\n") == ["fox"]


def test_a_byte_order_mark_and_blank_input_are_handled():
    assert parse_names("﻿Timestamp,Team name\n1,fox\n") == ["fox"]
    assert parse_names("") == []
    assert parse_names("Timestamp,Team name\n") == []


def test_the_list_is_capped():
    rows = "".join(f"1,team{i}\n" for i in range(MAX_NAMES + 50))
    assert len(parse_names("Timestamp,Team name\n" + rows)) == MAX_NAMES


def test_statuses_say_whether_a_bot_exists_for_the_name():
    assert roster(["fox", "owl"], ["owl", "bear"]) == [
        ("bear", "submitted"),
        ("fox", "registered"),
        ("owl", "submitted"),
    ]


# -- fetching it -------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "data")


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_a_file_is_read_and_remembered(store, tmp_path):
    sheet = tmp_path / "r.csv"
    sheet.write_text(SHEET, encoding="utf-8")
    names, warning = load_registered(str(sheet), store)
    assert names == ["fox", "owl", "bear-2"] and warning is None
    sheet.unlink()  # the file goes missing: the last list is used
    names, warning = load_registered(str(sheet), store)
    assert names == ["fox", "owl", "bear-2"]
    assert "last list that was read" in warning


def test_no_source_means_no_names(store):
    assert load_registered("", store) == ([], None)


def test_an_unreadable_sheet_with_nothing_remembered_is_an_error(store):
    with pytest.raises(RosterError, match="cannot read"):
        load_registered("/no/such/file.csv", store)


def test_an_https_address_is_fetched(store, monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        return FakeResponse(SHEET.encode())

    monkeypatch.setattr("arena.roster.urllib.request.urlopen", fake_urlopen)
    names, _ = load_registered(SHEET_URL, store)
    assert names == ["fox", "owl", "bear-2"]
    assert seen["url"].startswith("https://docs.google.com/")
    assert 0 < seen["timeout"] <= 60


def test_a_failed_fetch_keeps_the_last_good_list(store, monkeypatch):
    calls = []

    def flaky(request, timeout):
        calls.append(1)
        if len(calls) > 1:
            raise urllib.error.URLError("network down")
        return FakeResponse(SHEET.encode())

    monkeypatch.setattr("arena.roster.urllib.request.urlopen", flaky)
    first, warning = load_registered(SHEET_URL, store)
    second, warning2 = load_registered(SHEET_URL, store)
    assert warning is None and second == first
    assert "network down" in warning2


@pytest.mark.parametrize(
    "source",
    [
        "http://example.com/x.csv",
        "ftp://example.com/x.csv",
        "file:///etc/passwd",
    ],
)
def test_only_https_addresses_are_fetched(store, source):
    with pytest.raises(RosterError, match="https://"):
        load_registered(source, store)


def test_an_oversized_sheet_is_refused(store, monkeypatch):
    monkeypatch.setattr("arena.roster.MAX_BYTES", 100)
    monkeypatch.setattr(
        "arena.roster.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(b"x" * 500),
    )
    with pytest.raises(RosterError, match="too large"):
        load_registered(SHEET_URL, store)


# -- the form address --------------------------------------------------------


def test_the_register_form_address_must_be_a_prefilled_google_form_link():
    assert REGISTER_FORM.match(FORM)
    for bad in [
        "",
        "http://docs.google.com/forms/d/e/ID/viewform?entry.1=",
        "https://evil.example/forms/d/e/ID/viewform?entry.1=",
        "https://docs.google.com/forms/d/e/ID/viewform",
        "https://docs.google.com/forms/d/e/ID/viewform?entry.1=already",
        "https://docs.google.com/forms/d/e/ID/viewform?entry.1= <script>",
        "javascript:alert(1)//viewform?entry.1=",
    ]:
        assert not REGISTER_FORM.match(bad), bad
    with pytest.raises(ExportError, match="prefilled link"):
        ExportOptions(register_form="https://example.com/").validate()
    ExportOptions(register_form=FORM).validate()


# -- what the site is given --------------------------------------------------


def add_team(store, team):
    store.add_version(team, f"h-{team}", "", "valid", "")
    store.set_current(team, f"h-{team}")


def exported(store, out, **options):
    summary = export_site(store.root, out, ExportOptions(**options))
    data = out / "data"
    return summary, {
        "teams": json.loads((data / "teams.json").read_text(encoding="utf-8")),
        "manifest": json.loads(
            (data / "manifest.json").read_text(encoding="utf-8")
        ),
    }


def write_sheet(tmp_path):
    sheet = tmp_path / "r.csv"
    sheet.write_text(SHEET, encoding="utf-8")
    return sheet


def test_the_roster_shows_registered_and_submitted_names(store, tmp_path):
    sheet = write_sheet(tmp_path)
    ensure_tournament(store)
    add_team(store, "owl")  # registered AND has a bot
    add_team(store, "wasp")  # has a bot but never registered
    _, got = exported(store, tmp_path / "site", registrations=str(sheet))
    status = {t["team"]: t["status"] for t in got["teams"]["teams"]}
    assert status == {
        "bear-2": "registered",
        "fox": "registered",
        "owl": "submitted",
        "wasp": "submitted",
    }


def test_a_name_updates_to_submitted_when_its_bot_is_imported(store, tmp_path):
    sheet = write_sheet(tmp_path)
    ensure_tournament(store)
    out = tmp_path / "site"
    first, before = exported(store, out, registrations=str(sheet))
    assert {t["status"] for t in before["teams"]["teams"]} == {"registered"}

    add_team(store, "fox")  # fox's zip is imported
    second, after = exported(store, out, registrations=str(sheet))
    fox = next(t for t in after["teams"]["teams"] if t["team"] == "fox")
    assert fox["status"] == "submitted"
    assert second.changed  # so the site is republished
    unchanged, _ = exported(store, out, registrations=str(sheet))
    assert unchanged.changed is False


def test_registered_names_stay_listed_after_the_draw(store, tmp_path):
    sheet = write_sheet(tmp_path)
    for team in ("owl", "wasp"):
        add_team(store, team)
    ensure_tournament(store)
    draw(store, group_size=8, seed=1)
    _, got = exported(store, tmp_path / "site", registrations=str(sheet))
    groups = {t["team"]: t["group"] for t in got["teams"]["teams"]}
    assert groups["owl"] == "A" and groups["wasp"] == "A"
    assert groups["fox"] is None  # registered, but not in the draw


def test_an_unreadable_sheet_does_not_blank_the_roster(store, tmp_path):
    sheet = write_sheet(tmp_path)
    ensure_tournament(store)
    out = tmp_path / "site"
    exported(store, out, registrations=str(sheet))
    sheet.unlink()
    summary, got = exported(store, out, registrations=str(sheet))
    assert "last list that was read" in summary.warning
    assert len(got["teams"]["teams"]) == 3


def test_the_manifest_carries_the_form_address_only_when_set(store, tmp_path):
    ensure_tournament(store)
    _, off = exported(store, tmp_path / "a")
    _, on = exported(store, tmp_path / "b", register_form=FORM)
    assert off["manifest"]["register_form"] is None
    assert on["manifest"]["register_form"] == FORM


def test_registered_names_carry_no_results(store, tmp_path):
    sheet = write_sheet(tmp_path)
    ensure_tournament(store)
    out = tmp_path / "site"
    exported(store, out, registrations=str(sheet))
    everything = "".join(
        p.read_text(encoding="utf-8") for p in (out / "data").glob("*.json")
    )
    for word in ("mean_bb", "ci95", '"score"', "wins"):
        assert word not in everything


def test_the_export_command_takes_both_options(store, tmp_path, capsys):
    sheet = write_sheet(tmp_path)
    ensure_tournament(store)
    out = tmp_path / "site"
    base = ["export", "--root", str(store.root), "--out", str(out)]
    code = main(
        base + ["--registrations", str(sheet), "--register-form", FORM]
    )
    assert code == 0
    manifest = json.loads((out / "data" / "manifest.json").read_text())
    assert manifest["register_form"] == FORM
    sheet.unlink()
    main(base + ["--registrations", str(sheet)])
    assert "warning" in capsys.readouterr().out
