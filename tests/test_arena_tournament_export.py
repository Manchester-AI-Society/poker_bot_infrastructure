"""What the website is given during a tournament: nothing about how anyone
is doing until a round is complete."""

from __future__ import annotations

import json

import pytest

from arena.export import ExportOptions, export_site
from arena.gateway import hash_key
from arena.store import Store
from arena.tournament import (
    draw,
    generate_keys,
    settle,
    start_finals,
    start_groups,
    state_of,
)

TEAMS = ["ant", "bee", "cat", "dog", "eel", "fox"]
# Strength: earlier names beat later ones, so the order is known.
RANK = {name: i for i, name in enumerate(TEAMS)}


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "data")
    generate_keys(store, TEAMS)
    return store


def fake_result(a: str, b: str, deals=10) -> dict:
    """Result of a match in which the lower-ranked name wins by 1 bb."""
    mean = 1.0 if RANK[a] < RANK[b] else -1.0
    return {
        "a": a,
        "b": b,
        "a_team": a,
        "b_team": b,
        "deals_requested": deals,
        "deals_completed": deals,
        "mean_bb": mean,
        "se_bb": 0.25,
        "ci95_bb": 0.5,
        "hands_played": deals * 2,
        "faults_a": 0,
        "faults_b": 0,
        "disabled_a": None,
        "disabled_b": None,
        "think_a": 1.0,
        "think_b": 1.0,
        "elapsed": 1.0,
        "status": "complete",
    }


def play(store, kind, only=None):
    """Finishes queued jobs of a kind (all of them, or the first ``only``)."""
    done = 0
    for job in store.jobs_of(kind):
        if job["status"] != "queued":
            continue
        if only is not None and done >= only:
            break
        a = store.get_version(job["a_hash"]).team
        b = store.get_version(job["b_hash"]).team
        assert store.claim_job_by_id(job["id"], "test")
        store.finish_job(job["id"], fake_result(a, b), None)
        done += 1
    return done


def export(store, tmp_path):
    out = tmp_path / "site"
    summary = export_site(store.root, out, ExportOptions())
    files = {
        str(path.relative_to(out / "data")): path.read_text(encoding="utf-8")
        for path in (out / "data").rglob("*")
        if path.is_file()
    }
    return summary, files


RESULT_WORDS = ("mean_bb", "ci95", "score", "wins", "losses", "faults")


def assert_no_results(files):
    for name, text in files.items():
        for word in RESULT_WORDS:
            assert word not in text, f"{word!r} leaked into {name}"


def load(files, name):
    return json.loads(files[name])


def test_before_the_draw_the_site_is_told_only_the_roster(store, tmp_path):
    summary, files = export(store, tmp_path)
    manifest = load(files, "manifest.json")
    assert manifest["mode"] == "tournament"
    assert manifest["phase"] == "registration"
    assert manifest["kinds"] == [] and manifest["final_available"] is False
    assert load(files, "tournament.json")["groups"] == []
    assert [t["team"] for t in load(files, "teams.json")["teams"]] == TEAMS
    assert_no_results(files)
    assert summary.phase == "registration" and summary.teams == 6


def test_the_draw_is_public_but_has_no_results(store, tmp_path):
    draw(store, group_size=3, seed=5)
    _, files = export(store, tmp_path)
    view = load(files, "tournament.json")
    assert view["phase"] == "drawn"
    assert sorted(t for g in view["groups"] for t in g["teams"]) == TEAMS
    assert all(g["board"] is None for g in view["groups"])
    assert view["finals"] is None and view["champion"] is None
    assert not any(n.startswith(("pairings", "leaderboard")) for n in files)
    assert_no_results(files)


def test_while_round_one_is_played_nothing_about_it_is_published(
    store, tmp_path
):
    draw(store, group_size=3, seed=5)
    start_groups(store, deals=10)
    _, before = export(store, tmp_path)

    # Some, but not all, of the group matches are played.
    assert play(store, "group", only=4) == 4
    _, during = export(store, tmp_path)

    assert_no_results(during)
    assert not any(n.startswith(("pairings", "leaderboard")) for n in during)
    # And nothing changed at all, not even a count: so a git host is not
    # asked to redeploy once per match.
    assert during == before
    assert load(during, "manifest.json")["phase"] == "groups"


def test_round_one_results_appear_when_the_round_is_complete(store, tmp_path):
    draw(store, group_size=3, advance=2, seed=5)
    start_groups(store, deals=10)
    play(store, "group")
    assert settle(store) == "between"

    summary, files = export(store, tmp_path)
    view = load(files, "tournament.json")
    manifest = load(files, "manifest.json")
    assert manifest["kinds"] == ["group"] and not manifest["final_available"]
    for group in view["groups"]:
        board = group["board"]
        assert board["pairs_done"] == board["pairs_total"] == 3
        assert board["kind"] == "group"
        # In each group the better-named teams rank higher, by construction.
        names = [t["team"] for t in board["teams"]]
        assert names == sorted(names, key=RANK.get)
    # The qualifiers are the top two of each group.
    expected = [
        t["team"] for g in view["groups"] for t in g["board"]["teams"][:2]
    ]
    assert view["qualified"] == expected and len(expected) == 4
    pairings = load(files, "pairings-group.json")
    assert len(pairings) == 6 and {p["group"] for p in pairings} == {"A", "B"}
    # The final is NOT public yet.
    assert view["finals"] is None and view["champion"] is None
    assert "leaderboard-final.json" not in files
    assert summary.ladder_pairings == 6 and summary.final_pairings == 0


def test_the_final_is_hidden_until_it_is_complete(store, tmp_path):
    draw(store, group_size=3, advance=2, seed=5)
    start_groups(store, deals=10)
    play(store, "group")
    settle(store)
    start_finals(store, deals=10)
    play(store, "final", only=3)  # half of the 6 final matches
    _, files = export(store, tmp_path)

    view = load(files, "tournament.json")
    assert view["phase"] == "finals"
    # Who is in the final is public (round 1 is over); how it is going is not.
    assert view["finals"]["teams"] == view["qualified"]
    assert view["finals"]["board"] is None
    assert view["champion"] is None
    assert "leaderboard-final.json" not in files
    assert "pairings-final.json" not in files
    assert "final" not in load(files, "manifest.json")["kinds"]


def test_the_champion_is_published_when_the_final_is_over(store, tmp_path):
    draw(store, group_size=3, advance=2, seed=5)
    start_groups(store, deals=10)
    play(store, "group")
    settle(store)
    start_finals(store, deals=10)
    play(store, "final")
    assert settle(store) == "done"

    summary, files = export(store, tmp_path)
    view = load(files, "tournament.json")
    board = load(files, "leaderboard-final.json")
    assert view["phase"] == "done"
    assert board["pairs_done"] == board["pairs_total"] == 6
    assert view["champion"] == board["teams"][0]["team"]
    assert view["champion"] == min(view["qualified"], key=RANK.get)
    assert load(files, "manifest.json")["kinds"] == ["group", "final"]
    assert len(load(files, "pairings-final.json")) == 6
    assert summary.final_available and summary.final_pairings == 6


def test_results_disappear_again_if_the_state_is_rolled_back(store, tmp_path):
    """Withholding is decided from the stored phase every time, not remembered
    from an earlier export."""
    draw(store, group_size=3, advance=2, seed=5)
    start_groups(store, deals=10)
    play(store, "group")
    settle(store)
    export(store, tmp_path)  # publishes the group tables

    state = state_of(store)
    state["phase"] = "groups"  # e.g. the organiser restored an old backup
    store.set_tournament(state)
    _, files = export(store, tmp_path)
    assert_no_results(files)
    assert "pairings-group.json" not in files


def test_no_key_or_key_hash_is_ever_published(store, tmp_path):
    keys = {t: "k-" + t for t in TEAMS}
    for team, key in keys.items():
        store.set_remote_key(team, hash_key(key))
    draw(store, group_size=3, seed=5)
    start_groups(store, deals=10)
    play(store, "group")
    settle(store)
    _, files = export(store, tmp_path)
    everything = "\n".join(files.values())
    for team, key in keys.items():
        assert key not in everything
        assert hash_key(key) not in everything


def test_connection_status_is_not_published(store, tmp_path):
    """Whether a team's bot is online changes constantly; publishing it would
    redeploy the site every time anyone's Wi-Fi blinked."""
    draw(store, group_size=3, seed=5)
    _, before = export(store, tmp_path)
    store.set_presence("ant", True)
    store.set_presence("bee", True)
    store.set_presence("ant", False)
    _, after = export(store, tmp_path)
    assert after == before
    assert "connected" not in "".join(after.values())


def test_an_unchanged_tournament_is_not_republished(store, tmp_path):
    draw(store, group_size=3, seed=5)
    summary, _ = export(store, tmp_path)
    again, _ = export(store, tmp_path)
    assert again.changed is False
