"""Team registration through GitHub issues, tested against a fake GitHub."""

from __future__ import annotations

import pytest

from arena.registry import (
    GitHubError,
    Registration,
    Registry,
    decide,
    feedback_text,
    owner_of,
    parse_body,
    parse_issue,
)
from arena.store import Store


def body(team="fox", repo="https://github.com/alice/fox-bot", branch=None):
    """An issue body exactly as GitHub's issue form writes it."""
    return (
        f"### Team name\n\n{team}\n\n"
        f"### Repository URL\n\n{repo}\n\n"
        f"### Branch (optional)\n\n{branch or '_No response_'}\n"
    )


def issue(number, user, team="fox", repo=None, labels=(), branch=None, **more):
    repo = repo or f"https://github.com/{user}/{team}-bot"
    return {
        "number": number,
        "user": {"login": user},
        "body": body(team, repo, branch),
        "labels": [{"name": name} for name in labels],
        **more,
    }


def reg(number, user, team="fox", repo=None, labels=(), branch=None):
    parsed = parse_issue(issue(number, user, team, repo, labels, branch))
    assert parsed is not None
    return parsed


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "arena_data")


# -- reading an issue --------------------------------------------------


def test_the_form_body_is_read_into_its_fields():
    values = parse_body(body("fox", "https://github.com/a/b", "dev"))

    assert values == {
        "team": "fox",
        "repo": "https://github.com/a/b",
        "branch": "dev",
    }


def test_an_empty_optional_branch_means_no_branch():
    parsed = parse_issue(issue(1, "alice"))

    assert parsed.branch is None
    assert parsed.team == "fox" and parsed.user == "alice"


def test_team_names_are_lowercased_and_labels_too():
    parsed = parse_issue(issue(1, "alice", team="FoX", labels=["Approved"]))

    assert parsed.team == "fox" and parsed.labels == ("approved",)


@pytest.mark.parametrize(
    "text", ["", "just a question about the event", "### Something else\n\nx"]
)
def test_issues_that_are_not_registrations_are_ignored(text):
    assert (
        parse_issue({"number": 1, "user": {"login": "a"}, "body": text})
        is None
    )


def test_pull_requests_are_not_registrations():
    pr = issue(1, "alice", pull_request={"url": "x"})

    assert parse_issue(pr) is None


def test_the_owner_comes_from_the_address():
    assert owner_of("https://github.com/Alice/fox-bot") == "alice"
    assert owner_of("https://gitlab.com/alice/fox") == ""


# -- the rules ---------------------------------------------------------


def decisions(store, *regs, **options):
    return {d.registration.issue: d for d in decide(regs, store, **options)}


def test_an_owner_registration_waits_for_approval_by_default(store):
    result = decisions(store, reg(1, "alice"))

    assert result[1].status == "pending"
    assert "approval" in result[1].reason


def test_the_approved_label_accepts_it(store):
    result = decisions(store, reg(1, "alice", labels=["approved"]))

    assert result[1].status == "accepted"


def test_open_registration_accepts_without_a_label(store):
    result = decisions(store, reg(1, "alice"), open_registration=True)

    assert result[1].status == "accepted"


def test_you_cannot_register_a_repository_you_do_not_own(store):
    # Mallory opens an issue naming alice's repository, even though approved.
    result = decisions(
        store,
        reg(
            1,
            "mallory",
            repo="https://github.com/alice/fox-bot",
            labels=["approved"],
        ),
    )

    assert result[1].status == "rejected"
    assert "belongs to 'alice'" in result[1].reason
    assert "opened by 'mallory'" in result[1].reason


def test_owner_check_ignores_letter_case(store):
    result = decisions(
        store,
        reg(
            1,
            "Alice",
            repo="https://github.com/alice/Fox-Bot",
            labels=["approved"],
        ),
    )

    assert result[1].status == "accepted"


def test_the_organiser_can_verify_an_organisations_repository(store):
    result = decisions(
        store,
        reg(
            1,
            "alice",
            repo="https://github.com/the-club/bot",
            labels=["approved", "verified"],
        ),
    )

    assert result[1].status == "accepted"


@pytest.mark.parametrize(
    "repo",
    [
        "https://gitlab.com/alice/bot",
        "http://github.com/alice/bot",
        "git@github.com:alice/bot.git",
        "https://user:token@github.com/alice/bot",
        "https://github.com/alice",
        "file:///etc",
        "--upload-pack=x",
    ],
)
def test_only_plain_github_repository_addresses_are_accepted(store, repo):
    result = decisions(store, reg(1, "alice", repo=repo, labels=["approved"]))

    assert result[1].status == "rejected"


@pytest.mark.parametrize("team", ["Bad Name!", "", "x" * 40, "-x", "a/b"])
def test_bad_team_names_are_rejected(store, team):
    result = decisions(
        store,
        reg(1, "alice", team=team, labels=["approved"]),
        open_registration=True,
    )

    assert result[1].status == "rejected"
    assert "team name" in result[1].reason


def test_a_bad_branch_name_is_rejected(store):
    result = decisions(
        store,
        reg(1, "alice", branch="--upload-pack=x", labels=["approved"]),
    )

    assert result[1].status == "rejected"


def test_the_first_issue_keeps_a_team_name(store):
    result = decisions(
        store,
        reg(1, "alice", team="fox", labels=["approved"]),
        reg(2, "bob", team="fox", labels=["approved"]),
    )

    assert result[1].status == "accepted"
    assert result[2].status == "rejected"
    assert "already taken" in result[2].reason


def test_a_claimed_name_stays_with_its_owner_after_their_issue_is_gone(store):
    store.claim_team("fox", "alice", 1)

    # Alice's issue was closed; Bob now tries the name.
    result = decisions(store, reg(5, "bob", team="fox", labels=["approved"]))

    assert result[5].status == "rejected"
    assert "belongs to 'alice'" in result[5].reason


def test_editing_an_old_issue_cannot_steal_a_name_another_team_holds(store):
    # Bob's team "beta" was accepted and claimed. Alice's older issue #1 is
    # edited to say "beta": that must not take it, nor knock Bob out.
    store.claim_team("beta", "bob", 2)

    result = decisions(
        store,
        reg(1, "alice", team="beta", labels=["approved"]),
        reg(2, "bob", team="beta", labels=["approved"]),
    )

    assert result[1].status == "rejected"
    assert result[2].status == "accepted"


def test_one_account_may_hold_only_one_team_by_default(store):
    result = decisions(
        store,
        reg(1, "alice", team="fox", labels=["approved"]),
        reg(2, "alice", team="owl", labels=["approved"]),
    )

    assert result[1].status == "accepted"
    assert result[2].status == "rejected"
    assert "one account may register 1 team" in result[2].reason


def test_the_limit_per_account_can_be_raised(store):
    result = decisions(
        store,
        reg(1, "alice", team="fox", labels=["approved"]),
        reg(2, "alice", team="owl", labels=["approved"]),
        max_per_user=2,
    )

    assert {d.status for d in result.values()} == {"accepted"}


def test_a_repository_belongs_to_one_team(store):
    result = decisions(
        store,
        reg(
            1,
            "alice",
            team="fox",
            repo="https://github.com/alice/bot",
            labels=["approved"],
        ),
        reg(
            2,
            "alice",
            team="owl",
            repo="https://github.com/Alice/bot.git",
            labels=["approved"],
        ),
        max_per_user=2,
    )

    assert result[2].status == "rejected"
    assert "already registered by 'fox'" in result[2].reason


def test_a_later_issue_by_the_same_account_changes_the_repository(store):
    result = decisions(
        store,
        reg(
            1,
            "alice",
            team="fox",
            repo="https://github.com/alice/old",
            labels=["approved"],
        ),
        reg(
            4,
            "alice",
            team="fox",
            repo="https://github.com/alice/new",
            labels=["approved"],
        ),
    )

    accepted = [d for d in result.values() if d.status == "accepted"]
    assert [d.registration.repo for d in accepted] == [
        "https://github.com/alice/new"
    ]


def test_a_rejected_registration_never_blocks_the_name_for_the_real_owner(
    store,
):
    # Mallory's bad attempt (not the owner) comes first; it must not claim
    # "fox" and lock alice out.
    result = decisions(
        store,
        reg(
            1,
            "mallory",
            team="fox",
            repo="https://github.com/alice/fox-bot",
            labels=["approved"],
        ),
        reg(2, "alice", team="fox", labels=["approved"]),
    )

    assert result[1].status == "rejected"
    assert result[2].status == "accepted"


# -- the Registry: issues in, teams out --------------------------------


class FakeGitHub:
    def __init__(self, issues=()):
        self.issue_list = list(issues)
        self.comments = []
        self.fail = None
        self.can_comment = True

    def issues(self):
        if self.fail:
            raise GitHubError(self.fail)
        return self.issue_list

    def comment(self, number, text):
        if not self.can_comment:
            return False
        self.comments.append((number, text))
        return True


def lines():
    said = []
    return said, said.append


def test_accepted_registrations_become_teams_to_pull(store):
    github = FakeGitHub(
        [
            issue(1, "alice", "fox", labels=["approved"]),
            issue(2, "bob", "owl"),  # not approved yet
            {"number": 3, "user": {"login": "carol"}, "body": "a question"},
        ]
    )
    said, report = lines()

    sources = Registry(github, store).current(report)

    assert [(s.team, s.url) for s in sources] == [
        ("fox", "https://github.com/alice/fox-bot")
    ]
    saved = store.registrations()
    assert saved[1]["status"] == "accepted"
    assert saved[2]["status"] == "pending"
    assert 3 not in saved  # not a registration at all


def test_accepting_a_team_claims_its_name(store):
    github = FakeGitHub([issue(1, "alice", "fox", labels=["approved"])])

    Registry(github, store).current(lambda m: None)

    assert store.team_claim("fox")["user"] == "alice"


def test_approving_later_turns_pending_into_a_team(store):
    github = FakeGitHub([issue(1, "alice", "fox")])
    registry = Registry(github, store)
    assert registry.current(lambda m: None) == []

    github.issue_list = [issue(1, "alice", "fox", labels=["approved"])]
    sources = registry.current(lambda m: None)

    assert [s.team for s in sources] == ["fox"]


def test_a_closed_issue_withdraws_the_registration(store):
    github = FakeGitHub([issue(1, "alice", "fox", labels=["approved"])])
    registry = Registry(github, store)
    registry.current(lambda m: None)

    github.issue_list = []  # the open-issues list no longer has it
    sources = registry.current(lambda m: None)

    assert sources == []
    assert store.registrations() == {}


def test_each_outcome_is_told_to_the_registrant_once(store):
    github = FakeGitHub(
        [
            issue(1, "alice", "fox", labels=["approved"]),
            issue(2, "bob", "owl", repo="https://github.com/alice/stolen"),
        ]
    )
    registry = Registry(github, store)

    registry.current(lambda m: None)
    registry.current(lambda m: None)  # a second pass: same outcomes
    registry.current(lambda m: None)

    numbers = [n for n, _ in github.comments]
    assert sorted(numbers) == [1, 2]  # one comment each, not three
    texts = dict(github.comments)
    assert "Registered as **fox**" in texts[1]
    assert "not accepted" in texts[2] and "belongs to 'alice'" in texts[2]


def test_a_changed_outcome_is_told_again(store):
    github = FakeGitHub([issue(1, "alice", "fox")])
    registry = Registry(github, store)
    registry.current(lambda m: None)

    github.issue_list = [issue(1, "alice", "fox", labels=["approved"])]
    registry.current(lambda m: None)

    assert [("waiting" in t) for _, t in github.comments] == [True, False]


def test_when_comments_are_impossible_registration_still_works(store):
    github = FakeGitHub([issue(1, "alice", "fox", labels=["approved"])])
    github.can_comment = False
    said, report = lines()

    sources = Registry(github, store).current(report)

    assert [s.team for s in sources] == ["fox"]
    assert any("cannot comment" in line for line in said)


def test_if_github_cannot_be_reached_the_last_good_list_is_kept(store):
    github = FakeGitHub([issue(1, "alice", "fox", labels=["approved"])])
    registry = Registry(github, store)
    assert [s.team for s in registry.current(lambda m: None)] == ["fox"]
    said, report = lines()

    github.fail = "cannot reach GitHub: timed out"
    first = registry.current(report)
    second = registry.current(report)

    assert [s.team for s in first] == ["fox"] == [s.team for s in second]
    assert len(said) == 1  # reported once, not every pass
    assert "keeping the previous list" in said[0]


def test_feedback_can_be_switched_off(store):
    github = FakeGitHub([issue(1, "alice", "fox", labels=["approved"])])

    Registry(github, store, feedback=False).current(lambda m: None)

    assert github.comments == []


def test_every_outcome_has_a_plain_message():
    r = Registration(1, "alice", "fox", "https://github.com/alice/b", None, ())
    from arena.registry import Decision

    assert "fetched within a minute" in feedback_text(Decision(r, "accepted"))
    assert "approval" in feedback_text(Decision(r, "pending", "x"))
    assert "not accepted" in feedback_text(Decision(r, "rejected", "because"))
