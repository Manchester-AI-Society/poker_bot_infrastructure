"""The live feed: the server's play, delayed, as static files."""

from __future__ import annotations

import asyncio
import json

import pytest

from arena import live
from arena.cli import main
from arena.export import ExportError
from arena.live import (
    Feed,
    LiveOptions,
    build_files,
    export_live,
    parse_events,
)
from game.game_domain_models import InvalidActionError
from tests.engine_helpers import act, new_match, rig

# -- a real match from the real engine ------------------


def engine_log():
    """Three real hands: a fold, a showdown, then the hand limit."""

    async def scenario():
        service, runtime = await new_match([1000, 1000], max_hands=3)
        await act(service, runtime, "raise_to", 60)
        await act(service, runtime, "fold")  # hand 1: won by fold
        rig(runtime, {0: "AS AH", 1: "7C 2D"}, "KD 9S 4H 3C JD")
        for _ in range(12):  # hand 2: checked or called down
            if (
                len([e for e in runtime.action_log if e["type"] == "showdown"])
                > 1
            ):
                break
            try:
                await act(service, runtime, "check")
            except InvalidActionError:
                await act(service, runtime, "call")
        await act(service, runtime, "raise_to", 60)
        await act(service, runtime, "fold")  # hand 3: won by fold
        return list(runtime.action_log)

    return asyncio.run(scenario())


def test_real_hands_are_assembled_from_the_event_log():
    parsed = parse_events(engine_log())
    assert [h["n"] for h in parsed["hands"]] == [1, 2, 3]
    assert parsed["players"] == ["p0", "p1"] and parsed["created"]
    first = parsed["hands"][0]
    assert first["players"] == ["p0", "p1"]
    assert first["stacks"] == {"p0": 1000, "p1": 1000}
    assert [s["type"] for s in first["steps"]] == ["action", "action"]
    assert first["showdown"]["hole_cards"] is None  # a fold shows nothing
    assert first["showdown"]["results"][0]["hand"] in ("Won by Fold", "Folded")
    assert parsed["ended"] and parsed["ended"]["reason"] == "hand_limit"


def test_only_the_showdown_hand_has_hole_cards_and_a_board():
    hands = parse_events(engine_log())["hands"]
    shown = [h for h in hands if h["showdown"]["hole_cards"]]
    assert [h["n"] for h in shown] == [2]
    assert shown[0]["showdown"]["hole_cards"] == {
        "p0": ["AS", "AH"],
        "p1": ["7C", "2D"],
    }
    streets = [s["street"] for s in shown[0]["steps"] if s["type"] == "street"]
    assert streets[:3] == ["flop", "turn", "river"]
    # Chips are conserved through every hand.
    for hand in hands:
        assert sum(hand["showdown"]["stacks"].values()) == 2000


def test_a_hand_still_being_played_is_left_out():
    events = engine_log()
    cut = max(i for i, e in enumerate(events) if e["type"] == "hand_started")
    parsed = parse_events(events[: cut + 2])  # hand 3 has started, not ended
    assert [h["n"] for h in parsed["hands"]] == [1, 2]
    assert parsed["ended"] is None


# -- synthetic matches for timing ------------------


def synthetic(t0, hands=2, finish=True, players=("a", "b"), winner="a"):
    """A tiny match: each hand takes 30 s; the match ends right after."""
    events = [
        {"type": "match_created", "timestamp": t0, "player_ids": list(players)}
    ]
    stacks = {p: 100 for p in players}
    for n in range(1, hands + 1):
        start = t0 + 1 + (n - 1) * 30
        events.append(
            {
                "type": "hand_started",
                "timestamp": start,
                "hand_number": n,
                "dealer_index": 0,
                "eliminated": [],
                "players": list(players),
                "stacks": dict(stacks),
                "blinds": [
                    {"player_id": players[0], "amount": 1},
                    {"player_id": players[1], "amount": 2},
                ],
            }
        )
        events.append(
            {
                "type": "action",
                "timestamp": start + 5,
                "player_id": players[0],
                "action": "fold",
                "amount": None,
                "street": "preflop",
                "pot": 3,
                "stack": stacks[players[0]] - 1,
                "bet": 1,
            }
        )
        stacks = {
            players[0]: stacks[players[0]] - 1,
            players[1]: stacks[players[1]] + 1,
        }
        events.append(
            {
                "type": "showdown",
                "timestamp": start + 20,
                "results": [
                    {
                        "player_id": players[1],
                        "hand": "Won by Fold",
                        "winnings": 3,
                    },
                    {"player_id": players[0], "hand": "Folded", "winnings": 0},
                ],
                "stacks": dict(stacks),
            }
        )
    if finish:
        events.append(
            {
                "type": "match_ended",
                "timestamp": t0 + 1 + hands * 30,
                "reason": "hand_limit",
                "winner_ids": [winner],
            }
        )
    return events


class FakeServer:
    """Stands in for the poker server's HTTP API."""

    def __init__(self):
        self.tournament = {
            "status": "idle",
            "round": 0,
            "entrants": [],
            "tables": [],
            "completed_rounds": [],
            "champion": None,
        }
        self.lobby = []
        self.events = {}
        self.calls = []

    def __call__(self, base_url, path, timeout=10.0):
        self.calls.append(path)
        if path == "/v1/tournament":
            return json.loads(json.dumps(self.tournament))
        if path == "/v1/lobby":
            return {"players": list(self.lobby)}
        if path.startswith("/v1/matches/") and "/events" in path:
            match_id = path.split("/")[3]
            if match_id not in self.events:
                raise live.ServerError(f"{path}: HTTP 404")
            query = dict(q.split("=") for q in path.split("?")[1].split("&"))
            offset, limit = int(query["offset"]), int(query["limit"])
            events = self.events[match_id]
            return {
                "events": events[offset : offset + limit],
                "total": len(events),
                "has_more": offset + limit < len(events),
            }
        raise live.ServerError(f"{path}: HTTP 404")


@pytest.fixture
def server(monkeypatch):
    fake = FakeServer()
    monkeypatch.setattr(live, "fetch_json", fake)
    return fake


def two_round_server(server, t0, final_done=True):
    """Round 1: two tables (m1: a v b, m2: c v d); final: m3 (a v c)."""
    server.events = {
        "m1": synthetic(t0, players=("a", "b"), winner="a"),
        "m2": synthetic(t0, players=("c", "d"), winner="c"),
        "m3": synthetic(
            t0 + 200, players=("a", "c"), winner="a", finish=final_done
        ),
    }
    server.tournament = {
        "status": "finished" if final_done else "running",
        "round": 2,
        "entrants": ["a", "b", "c", "d"],
        "tables": [
            {"match_id": "m3", "player_ids": ["a", "c"], "winner": "a"}
        ],
        "completed_rounds": [
            [
                {"match_id": "m1", "player_ids": ["a", "b"], "winner": "a"},
                {"match_id": "m2", "player_ids": ["c", "d"], "winner": "c"},
            ]
        ],
        "champion": "a" if final_done else None,
    }


def built(feed, now, delay=100.0):
    files = build_files(feed, now, delay, {"server_url": None})
    return {name: json.loads(text) for name, text in files.items()}


# -- reading a server ------------------


def test_the_feed_follows_the_whole_bracket_and_pages_through_events(
    server, monkeypatch
):
    monkeypatch.setattr(live, "PAGE", 3)  # force several pages per match
    two_round_server(server, 1000.0)
    feed = Feed("http://server")
    feed.poll()
    assert sorted(feed.tables) == ["m1", "m2", "m3"]
    assert feed.tables["m1"].round == 1 and feed.tables["m3"].round == 2
    assert len(feed.tables["m1"].events) == len(server.events["m1"])
    paged = [c for c in server.calls if "m1/events" in c]
    assert len(paged) > 1
    # A second poll only asks for what is new.
    before = len(feed.tables["m1"].events)
    feed.poll()
    assert len(feed.tables["m1"].events) == before


def test_new_events_are_picked_up_on_the_next_poll(server):
    server.events = {"m1": synthetic(1000.0, hands=1, finish=False)}
    server.tournament.update(
        status="running",
        tables=[{"match_id": "m1", "player_ids": ["a", "b"], "winner": None}],
    )
    feed = Feed("http://server")
    feed.poll()
    seen = len(feed.tables["m1"].events)
    server.events["m1"] = synthetic(1000.0, hands=2, finish=True)
    feed.poll()
    assert len(feed.tables["m1"].events) > seen


def test_an_unreachable_server_keeps_what_was_seen(server):
    two_round_server(server, 1000.0)
    feed = Feed("http://server")
    feed.poll()
    tables = dict(feed.tables)

    def down(*args, **kwargs):
        raise live.ServerError("connection refused")

    live.fetch_json = down
    try:
        feed.poll()
    finally:
        live.fetch_json = server
    assert feed.last_error == "connection refused"
    assert feed.tables == tables


def test_a_reset_server_clears_the_old_tournament(server):
    two_round_server(server, 1000.0)
    feed = Feed("http://server")
    feed.poll()
    assert feed.tables
    server.tournament = {
        "status": "idle",
        "round": 0,
        "entrants": [],
        "tables": [],
        "completed_rounds": [],
        "champion": None,
    }
    server.events = {}
    server.lobby = ["x"]
    feed.poll()
    assert feed.tables == {} and feed.restarts == 1 and feed.lobby == ["x"]


# -- the delay ------------------


def test_a_hand_is_published_only_after_the_delay_has_passed(server):
    t0 = 1000.0
    server.events = {"m1": synthetic(t0, hands=2, finish=False)}
    server.tournament.update(
        status="running",
        entrants=["a", "b"],
        tables=[{"match_id": "m1", "player_ids": ["a", "b"], "winner": None}],
    )
    feed = Feed("http://server")
    feed.poll()
    # Hand 1 ends at t0+21, hand 2 at t0+51. delay 100.
    assert built(feed, t0 + 99)["live.json"]["status"] == "starting"
    # The table appears (empty) the moment the delay reaches its creation.
    assert built(feed, t0 + 100)["live.json"]["status"] == "running"
    early = built(feed, t0 + 100 + 21)
    assert early["live.json"]["status"] == "running"
    assert early["tables/m1.json"]["hands_played"] == 1
    mid = built(feed, t0 + 100 + 40)
    assert mid["tables/m1.json"]["hands_played"] == 1
    late = built(feed, t0 + 100 + 51)
    assert late["tables/m1.json"]["hands_played"] == 2
    assert [h["n"] for h in late["tables/m1.json"]["hands"]] == [1, 2]


def test_the_standings_are_those_of_the_delayed_view(server):
    t0 = 1000.0
    server.events = {"m1": synthetic(t0, hands=2, finish=False)}
    server.tournament.update(
        status="running",
        entrants=["a", "b"],
        tables=[{"match_id": "m1", "player_ids": ["a", "b"], "winner": None}],
    )
    feed = Feed("http://server")
    feed.poll()
    after_one = built(feed, t0 + 100 + 25)["tables/m1.json"]
    assert after_one["stacks"] == {"a": 99, "b": 101}
    after_two = built(feed, t0 + 100 + 60)["tables/m1.json"]
    assert after_two["stacks"] == {"a": 98, "b": 102}


def test_a_table_is_finished_only_when_the_delayed_view_reaches_its_end(
    server,
):
    t0 = 1000.0
    two_round_server(server, t0, final_done=False)
    feed = Feed("http://server")
    feed.poll()
    # m1 ends at t0+61.
    before = built(feed, t0 + 100 + 55)["tables/m1.json"]
    assert before["status"] == "playing" and before["winners"] == []
    after = built(feed, t0 + 100 + 65)["tables/m1.json"]
    assert after["status"] == "finished" and after["winners"] == ["a"]


def test_later_rounds_stay_hidden_until_the_delay_reaches_them(server):
    t0 = 1000.0
    two_round_server(server, t0)
    feed = Feed("http://server")
    feed.poll()
    # The final was created at t0+200: invisible until t0+200+delay.
    early = built(feed, t0 + 100 + 150)
    assert [r["round"] for r in early["live.json"]["rounds"]] == [1]
    assert "tables/m3.json" not in early
    later = built(feed, t0 + 100 + 210)
    assert [r["round"] for r in later["live.json"]["rounds"]] == [1, 2]


def test_the_champion_never_appears_before_the_final_has_finished_there(
    server,
):
    """The server already knows the champion; the site must not."""
    t0 = 1000.0
    two_round_server(server, t0)  # real time: all finished, champion known
    feed = Feed("http://server")
    feed.poll()
    # The delayed view is still in round 1, even with both tables finished.
    in_round_one = built(feed, t0 + 100 + 150)
    assert in_round_one["live.json"]["champion"] is None
    assert in_round_one["live.json"]["status"] == "running"
    assert in_round_one["teams.json"]["teams"] and all(
        t["status"] != "champion" for t in in_round_one["teams.json"]["teams"]
    )
    # In the final but not finished yet.
    in_final = built(feed, t0 + 100 + 240)
    assert in_final["live.json"]["champion"] is None
    # The final ends at t0+200+61.
    done = built(feed, t0 + 100 + 262)
    assert done["live.json"]["champion"] == "a"
    assert done["live.json"]["status"] == "finished"
    status = {t["team"]: t["status"] for t in done["teams.json"]["teams"]}
    assert status["a"] == "champion"


def test_one_visible_round_one_table_does_not_reveal_the_champion(server):
    """Tables that start at different times: when only one round-1 table is
    visible (and finished), the winner of the whole event must not show."""
    t0 = 1000.0
    two_round_server(server, t0)
    # The second round-1 table only started much later, so in the delayed
    # view round 1 consists of m1 alone.
    server.events["m2"] = synthetic(t0 + 150, players=("c", "d"), winner="c")
    feed = Feed("http://server")
    feed.poll()
    view = built(feed, t0 + 100 + 100)  # m1 done (t0+61), m2 not visible
    assert [
        t["match_id"] for t in view["live.json"]["rounds"][0]["tables"]
    ] == ["m1"]
    assert view["live.json"]["champion"] is None
    assert all(t["status"] != "champion" for t in view["teams.json"]["teams"])


def test_a_match_the_server_no_longer_has_is_skipped_quietly(server):
    two_round_server(server, 1000.0)
    del server.events["m2"]  # the server forgot this table
    feed = Feed("http://server")
    feed.poll()
    assert feed.tables["m2"].gone is True and feed.last_error is None
    asked = len([c for c in server.calls if "m2/events" in c])
    feed.poll()
    assert len([c for c in server.calls if "m2/events" in c]) == asked
    # Everything else is unaffected.
    assert len(feed.tables["m1"].events) == len(server.events["m1"])


def test_published_files_never_contain_the_real_time_champion_early(server):
    t0 = 1000.0
    two_round_server(server, t0)
    feed = Feed("http://server")
    feed.poll()
    files = build_files(feed, t0 + 100 + 150, 100.0, {})
    text = "".join(files.values())
    assert '"champion": "a"' not in text and '"champion":"a"' not in text


def test_before_the_start_only_the_lobby_is_shown(server):
    server.lobby = ["fox", "owl"]
    feed = Feed("http://server")
    feed.poll()
    out = built(feed, 5000.0)
    assert out["live.json"]["status"] == "idle"
    assert out["live.json"]["lobby"] == ["fox", "owl"]
    assert {t["team"]: t["status"] for t in out["teams.json"]["teams"]} == {
        "fox": "in the lobby",
        "owl": "in the lobby",
    }


def test_eliminated_teams_are_marked_out(server):
    t0 = 1000.0
    two_round_server(server, t0, final_done=False)
    feed = Feed("http://server")
    feed.poll()
    out = built(feed, t0 + 100 + 65)
    status = {t["team"]: t["status"] for t in out["teams.json"]["teams"]}
    assert status["a"] == "playing" and status["c"] == "playing"


def test_only_the_latest_hands_are_kept_in_a_table_file(server, monkeypatch):
    monkeypatch.setattr(live, "MAX_HANDS_SHOWN", 2)
    t0 = 1000.0
    server.events = {"m1": synthetic(t0, hands=5)}
    server.tournament.update(
        status="running",
        entrants=["a", "b"],
        tables=[{"match_id": "m1", "player_ids": ["a", "b"], "winner": None}],
    )
    feed = Feed("http://server")
    feed.poll()
    out = built(feed, t0 + 1000)["tables/m1.json"]
    assert out["hands_played"] == 5
    assert [h["n"] for h in out["hands"]] == [4, 5]


# -- writing the site ------------------


def options(**more):
    return LiveOptions(delay=100.0, interval=300.0, **more)


def test_the_site_and_data_are_written_and_not_rewritten(server, tmp_path):
    t0 = 1000.0
    two_round_server(server, t0)
    feed = Feed("http://server")
    feed.poll()
    out = tmp_path / "site"
    opts = options(
        server_url="https://example.trycloudflare.com",
        form_url="https://forms.example/backup",
        register_form=(
            "https://docs.google.com/forms/d/e/ID/viewform?usp=pp_url&entry.1="
        ),
        guide="# Info\n\nhello\n",
    )
    assert export_live(feed, out, opts, now=t0 + 400) is True
    data = out / "data"
    assert (out / "index.html").exists()
    manifest = json.loads((data / "manifest.json").read_text())
    assert manifest["mode"] == "live" and manifest["has_guide"] is True
    assert manifest["register_form"] == opts.register_form
    info = json.loads((data / "info.json").read_text())
    assert info["server_url"] == "https://example.trycloudflare.com"
    assert info["join_code"] is None  # not published unless asked
    assert (data / "submitting.md").read_text().startswith("# Info")
    assert sorted(p.name for p in (data / "tables").glob("*.json")) == [
        "m1.json",
        "m2.json",
        "m3.json",
    ]
    assert export_live(feed, out, opts, now=t0 + 400) is False  # unchanged


def test_the_join_code_is_published_only_when_asked(server, tmp_path):
    feed = Feed("http://server")
    feed.poll()
    out = tmp_path / "site"
    export_live(feed, out, options(join_code="abc123"), now=5000.0)
    info = json.loads((out / "data" / "info.json").read_text())
    assert info["join_code"] == "abc123"


def test_files_of_the_other_modes_and_old_tables_are_removed(server, tmp_path):
    out = tmp_path / "site"
    data = out / "data"
    (data / "tables").mkdir(parents=True)
    for name in (
        "tournament.json",
        "leaderboard-final.json",
        "pairings-final.json",
    ):
        (data / name).write_text("{}")
    (data / "tables" / "old.json").write_text("{}")
    feed = Feed("http://server")
    feed.poll()
    export_live(feed, out, options(), now=5000.0)
    assert not (data / "tournament.json").exists()
    assert not (data / "leaderboard-final.json").exists()
    assert not (data / "pairings-final.json").exists()
    assert not (data / "tables" / "old.json").exists()


def test_registered_names_are_listed_before_anyone_joins(server, tmp_path):
    sheet = tmp_path / "r.csv"
    sheet.write_text("Timestamp,Team name\n1,fox\n2,owl\n", encoding="utf-8")
    server.lobby = ["fox"]
    feed = Feed("http://server")
    feed.poll()
    out = tmp_path / "site"
    export_live(feed, out, options(registrations=str(sheet)), now=5000.0)
    teams = json.loads((out / "data" / "teams.json").read_text())["teams"]
    assert {t["team"]: t["status"] for t in teams} == {
        "fox": "in the lobby",
        "owl": "registered",
    }


# -- settings ------------------


def test_publishing_too_often_is_refused():
    with pytest.raises(ExportError, match="deployments"):
        LiveOptions(interval=10).validate()
    with pytest.raises(ExportError, match="negative"):
        LiveOptions(delay=-1).validate()
    with pytest.raises(ExportError, match="http"):
        LiveOptions(server="localhost:8000").validate()
    LiveOptions(interval=60).validate()


def test_the_command_publishes_once(server, tmp_path, capsys):
    two_round_server(server, 1000.0)
    out = tmp_path / "site"
    code = main(
        [
            "live",
            "--once",
            "--out",
            str(out),
            "--server",
            "http://server",
            "--delay",
            "0",
            "--no-guide",
        ]
    )
    assert code == 0
    assert (out / "data" / "live.json").exists()
    printed = capsys.readouterr().out
    assert "behind the game" in printed and "deployments" in printed


def test_the_command_warns_when_it_will_publish_the_join_code(
    server, tmp_path, capsys
):
    out = tmp_path / "site"
    main(
        [
            "live",
            "--once",
            "--out",
            str(out),
            "--server",
            "http://server",
            "--no-guide",
            "--join-code",
            "abc123",
        ]
    )
    assert "join code will be PUBLISHED" in capsys.readouterr().out
