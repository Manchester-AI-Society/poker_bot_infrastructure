"""Submission zips: packing, importing, and refusing hostile archives."""

from __future__ import annotations

import json
import os
import textwrap
import time
import zipfile
from pathlib import Path

import pytest

from arena.cli import main
from arena.intake import SubmissionError, content_hash
from arena.package import (
    MANIFEST,
    PackError,
    find_zips,
    import_submissions,
    pack,
    unpack,
)
from arena.store import Store

HEADER = (
    "from player_sdk.bot_interface import PokerBot\n"
    "from player_sdk.models import Response\n"
)
CALLER = """
class Caller(PokerBot):
    def act(self, game_state):
        return Response.call()
"""
FOLDER = """
class Folder(PokerBot):
    def act(self, game_state):
        return Response.fold()
"""
WRONG_SIZE = """
class Wrong(PokerBot):
    def act(self, game_state):
        return Response.raise_to(1)
"""
CRASHES = """
class Crashes(PokerBot):
    def act(self, game_state):
        raise RuntimeError("boom")
"""


def make_bot(base: Path, name: str, body: str, extra=None) -> Path:
    folder = base / name
    folder.mkdir(parents=True)
    (folder / "bot.py").write_text(HEADER + textwrap.dedent(body))
    for relative, text in (extra or {}).items():
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return folder


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "arena_data")


@pytest.fixture
def work(tmp_path):
    return tmp_path / "work"


def good_zip(work, team="fox", body=CALLER, extra=None, out=None):
    bot = make_bot(work / "src", f"{team}-src-{time.time_ns()}", body, extra)
    return pack(bot, team, out or work / "out", validate=False).path


def raw_zip(path: Path, entries: dict, manifest=True, **manifest_fields):
    """Writes a zip from {name: bytes|str}, with a matching manifest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        if manifest:
            body = {
                "format": 1,
                "team": "fox",
                "digest": "0" * 12,
                "created": time.time(),
                **manifest_fields,
            }
            archive.writestr(MANIFEST, json.dumps(body))
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


# -- packing ---------------------


def test_a_good_bot_is_packed_into_a_zip_with_a_manifest(work):
    bot = make_bot(work, "fox", CALLER, {"data/table.json": "{}"})
    result = pack(bot, "fox", work / "out")
    assert result.path.name == "fox.zip" and result.files == 2
    with zipfile.ZipFile(result.path) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read(MANIFEST))
    assert names == {MANIFEST, "bot.py", "data/table.json"}
    assert manifest["team"] == "fox" and manifest["digest"] == result.digest
    assert manifest["digest"] == content_hash(bot)


def test_a_single_file_bot_is_packed_as_bot_py(work):
    source = work / "mybot.py"
    source.parent.mkdir(parents=True)
    source.write_text(HEADER + textwrap.dedent(CALLER))
    result = pack(source, "fox", work / "out")
    with zipfile.ZipFile(result.path) as archive:
        assert "bot.py" in archive.namelist()


def test_junk_is_left_out_of_the_zip(work):
    bot = make_bot(
        work,
        "fox",
        CALLER,
        {
            "__pycache__/x.pyc": "junk",
            ".git/config": "junk",
            ".venv/lib/x.py": "junk",
            "notes.txt": "keep",
        },
    )
    result = pack(bot, "fox", work / "out", validate=False)
    with zipfile.ZipFile(result.path) as archive:
        assert set(archive.namelist()) == {MANIFEST, "bot.py", "notes.txt"}


@pytest.mark.parametrize("team", ["Fox", "a b", "-x", "", "x" * 33, "../x"])
def test_bad_team_names_are_not_packed(work, team):
    bot = make_bot(work, "fox", CALLER)
    with pytest.raises(PackError, match="team name"):
        pack(bot, team, work / "out", validate=False)


def test_a_folder_without_bot_py_is_not_packed(work):
    (work / "empty").mkdir(parents=True)
    with pytest.raises(PackError, match="bot.py"):
        pack(work / "empty", "fox", work / "out")
    with pytest.raises(PackError, match="not found"):
        pack(work / "nope", "fox", work / "out")


def test_a_bot_that_fails_its_check_is_not_packed_and_says_why(work):
    crashing = make_bot(work, "bad", CRASHES)
    with pytest.raises(PackError, match="fails its check"):
        pack(crashing, "fox", work / "out")
    wrong = make_bot(work, "wrong", WRONG_SIZE)
    with pytest.raises(PackError) as caught:
        pack(wrong, "fox", work / "out")
    assert "allowed range" in str(caught.value)  # the Response message
    assert not (work / "out" / "fox.zip").exists()


def test_a_bot_that_is_too_big_is_not_packed(work, monkeypatch):
    monkeypatch.setattr("arena.intake.MAX_BYTES", 1000)
    bot = make_bot(work, "fox", CALLER, {"model.bin": "x" * 5000})
    with pytest.raises(PackError, match="larger than"):
        pack(bot, "fox", work / "out", validate=False)


# -- the round trip ---------------------


def test_a_packed_zip_unpacks_to_the_same_bot(work):
    bot = make_bot(work, "fox", CALLER, {"data/table.json": "[1,2]"})
    result = pack(bot, "fox", work / "out", validate=False)
    dest = work / "unpacked"
    dest.mkdir()
    manifest = unpack(result.path, dest)
    assert manifest["team"] == "fox"
    assert content_hash(dest) == content_hash(bot) == result.digest
    assert (dest / "data" / "table.json").read_text() == "[1,2]"
    assert not (dest / MANIFEST).exists()  # it is not part of the bot


# -- hostile zips ---------------------


def unpack_error(path: Path, work: Path) -> str:
    dest = work / "dest"
    dest.mkdir(parents=True, exist_ok=True)
    with pytest.raises(SubmissionError) as caught:
        unpack(path, dest)
    return str(caught.value)


@pytest.mark.parametrize(
    "name",
    [
        "../evil.py",
        "a/../../evil.py",
        "/etc/passwd",
        "C:/Windows/evil.py",
        "C:\\evil.py",
        "..\\evil.py",
        "a\\..\\..\\evil.py",
    ],
)
def test_paths_that_escape_the_folder_are_refused_and_nothing_is_written(
    work, name
):
    path = raw_zip(work / "evil.zip", {"bot.py": "x = 1", name: "evil"})
    assert "unsafe path" in unpack_error(path, work)
    assert not (work.parent / "evil.py").exists()
    assert not (work / "evil.py").exists()
    assert list((work / "dest").rglob("*")) == []  # refused before extracting


def test_a_link_in_the_zip_is_refused(work):
    path = work / "link.zip"
    path.parent.mkdir(parents=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(MANIFEST, json.dumps({"format": 1, "team": "fox"}))
        info = zipfile.ZipInfo("bot.py")
        info.external_attr = (0o120777 << 16) | 0x20  # a symlink
        archive.writestr(info, "../../etc/passwd")
    assert "is a link" in unpack_error(path, work)


def test_the_same_file_twice_is_refused(work):
    path = work / "dup.zip"
    path.parent.mkdir(parents=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(MANIFEST, json.dumps({"format": 1, "team": "fox"}))
        archive.writestr("bot.py", "x = 1")
        archive.writestr("bot.py", "x = 2")
    assert "twice" in unpack_error(path, work)


def test_a_zip_bomb_is_refused(work):
    path = raw_zip(
        work / "bomb.zip",
        {"bot.py": "x = 1", "pad.bin": b"\0" * (8 * 1024 * 1024)},
    )
    assert path.stat().st_size < 100 * 1024
    assert "zip bomb" in unpack_error(path, work)


def test_a_zip_that_expands_past_the_size_limit_is_refused(work, monkeypatch):
    monkeypatch.setattr("arena.package.MAX_BYTES", 2000)
    path = raw_zip(
        work / "big.zip", {"bot.py": "x = 1", "m.bin": os.urandom(5000)}
    )
    assert "more than" in unpack_error(path, work)


def test_too_many_files_are_refused(work, monkeypatch):
    monkeypatch.setattr("arena.package.MAX_FILES", 3)
    path = raw_zip(work / "many.zip", {f"f{i}.py": "x" for i in range(6)})
    assert "too many files" in unpack_error(path, work)


def test_not_a_zip_is_refused(work):
    path = work / "junk.zip"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"this is not a zip file")
    assert "not a readable zip" in unpack_error(path, work)


def test_a_zip_without_a_manifest_or_with_a_bad_one_is_refused(work):
    no_manifest = raw_zip(work / "a.zip", {"bot.py": "x"}, manifest=False)
    assert MANIFEST in unpack_error(no_manifest, work)
    old = raw_zip(work / "b.zip", {"bot.py": "x"}, format=99)
    assert "different version" in unpack_error(old, work)
    nameless = raw_zip(work / "c.zip", {"bot.py": "x"}, team="Bad Name!")
    assert "no valid team" in unpack_error(nameless, work)


def test_a_zip_without_bot_py_is_refused(work):
    path = raw_zip(work / "d.zip", {"other.py": "x"})
    assert "bot.py" in unpack_error(path, work)


def test_files_changed_after_packing_are_refused(work):
    original = good_zip(work)
    tampered = work / "tampered.zip"
    with (
        zipfile.ZipFile(original) as src,
        zipfile.ZipFile(tampered, "w") as out,
    ):
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "bot.py":
                data += b"\n# edited after packing\n"
            out.writestr(item.filename, data)
    assert "checksum" in unpack_error(tampered, work)


# -- importing ---------------------


def test_the_importer_takes_every_zip_in_a_folder_tree(store, work):
    drop = work / "drive"
    good_zip(work, "fox", CALLER, out=drop / "responses (File responses)")
    good_zip(work, "owl", FOLDER, out=drop / "other folder" / "nested")
    # Google Drive appends the respondent's name to each file name.
    (drop / "x").mkdir(parents=True)
    results = import_submissions(store, drop, validate=False)
    assert sorted((r.team, r.status) for r in results) == [
        ("fox", "valid"),
        ("owl", "valid"),
    ]
    assert sorted(v.team for v in store.current_versions()) == ["fox", "owl"]
    assert len(find_zips(drop)) == 2


def test_the_importer_really_checks_the_bots(store, work):
    drop = work / "drop"
    good_zip(work, "fox", CALLER, out=drop)
    good_zip(work, "bad", CRASHES, out=drop)
    results = {r.team: r for r in import_submissions(store, drop)}
    assert results["fox"].status == "valid"
    assert (
        results["bad"].status == "invalid" and "boom" in results["bad"].message
    )
    assert [v.team for v in store.current_versions()] == ["fox"]


def test_a_team_that_submits_twice_is_played_with_its_newest_zip(store, work):
    drop = work / "drop"
    older = good_zip(work, "fox", CALLER, out=drop / "1")
    time.sleep(0.02)
    newer = good_zip(work, "fox", FOLDER, out=drop / "2")
    results = import_submissions(store, drop, validate=False)
    by_file = {r.file: r for r in results}
    assert older.parent.name == "1" and newer.parent.name == "2"
    statuses = sorted(r.status for r in results)
    assert statuses == ["superseded", "valid"]
    current = store.current_versions()
    assert len(current) == 1
    assert "Folder" in (Path(current[0].path) / "bot.py").read_text()
    assert by_file  # both files were read


def test_a_newer_zip_that_fails_never_replaces_a_working_one(store, work):
    drop = work / "drop"
    good_zip(work, "fox", CALLER, out=drop / "1")
    time.sleep(0.02)
    good_zip(work, "fox", CRASHES, out=drop / "2")
    results = import_submissions(store, drop)
    assert sorted(r.status for r in results) == ["invalid", "valid"]
    current = store.current_versions()
    assert len(current) == 1
    assert "Caller" in (Path(current[0].path) / "bot.py").read_text()


def test_copying_another_teams_code_is_rejected(store, work):
    drop = work / "drop"
    good_zip(work, "fox", CALLER, out=drop)
    time.sleep(0.02)
    good_zip(work, "owl", CALLER, out=drop)  # byte-identical code
    results = {
        r.team: r for r in import_submissions(store, drop, validate=False)
    }
    assert results["fox"].status == "valid"
    assert results["owl"].status == "rejected"
    assert "already submitted by 'fox'" in results["owl"].message


def test_bad_zips_in_the_folder_are_reported_and_do_not_stop_the_rest(
    store, work
):
    drop = work / "drop"
    good_zip(work, "fox", CALLER, out=drop)
    (drop / "junk.zip").write_bytes(b"nope")
    raw_zip(drop / "evil.zip", {"bot.py": "x", "../evil.py": "y"})
    results = import_submissions(store, drop, validate=False)
    assert sorted(r.status for r in results) == [
        "rejected",
        "rejected",
        "valid",
    ]
    assert not (drop.parent / "evil.py").exists()


# -- the commands ---------------------


def test_the_pack_and_import_commands(tmp_path, capsys):
    bot = make_bot(tmp_path / "src", "mybot", CALLER)
    out = tmp_path / "out"
    assert main(["pack", str(bot), "--team", "fox", "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "OK:" in text and "fox.zip" in text and "Upload" in text

    root = tmp_path / "root"
    assert main(["import", str(out), "--root", str(root)]) == 0
    text = capsys.readouterr().out
    assert "VALID" in text and "1 teams ready" in text

    assert (
        main(["import", str(tmp_path / "missing"), "--root", str(root)]) == 2
    )
    assert main(["import", str(tmp_path), "--root", str(root / "x")]) in (0, 1)


def test_the_pack_command_explains_a_failing_bot(tmp_path, capsys):
    bot = make_bot(tmp_path / "src", "mybot", WRONG_SIZE)
    code = main(["pack", str(bot), "--team", "fox", "--out", str(tmp_path)])
    assert code == 1
    text = capsys.readouterr().out
    assert "cannot pack" in text and "allowed range" in text
