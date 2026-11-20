from datetime import date, datetime, timedelta, timezone

import pytest

from app.radar.engine import ArtistFacts, evaluate, rank_key
from app.radar.rules import DEFAULT_RULES

TODAY = date(2026, 11, 19)


def days_ago(n):
    return TODAY - timedelta(days=n)


def make_facts(**overrides):
    data = {"artist_id": 1, "name": "Tems", "has_public_content": True}
    data.update(overrides)
    return ArtistFacts(**data)


def run(**overrides):
    return evaluate(make_facts(**overrides), DEFAULT_RULES, TODAY)


def names(evaluation):
    return [c.name for c in evaluation.components]


def check(evaluation, name):
    return next(c for c in evaluation.checks if c.name == name)


def test_a_typical_emerging_artist_is_scored_and_explained():
    news = datetime(2026, 11, 14, 9, 0, tzinfo=timezone.utc)
    ev = run(
        debut_year=2024, last_release_date=days_ago(20), last_update_at=news,
        listeners_latest=1704, listeners_base=1200, span_days=30,
    )

    assert ev.eligible and ev.appears and not ev.editors_pick
    assert names(ev) == ["growth", "new_release", "news_coverage", "new_career"]
    assert [c.points for c in ev.components] == [21, 25, 10, 10]
    assert ev.score == 66
    assert ev.components[0].detail == "Last.fm listeners up 42% in 30 days (1,200 to 1,704)."
    assert ev.growth_pct == pytest.approx(42.0)


def test_growth_points_are_capped():
    ev = run(listeners_latest=5000, listeners_base=1000, span_days=30, last_release_date=days_ago(400))
    assert [c.points for c in ev.components if c.name == "growth"] == [40]


@pytest.mark.parametrize(
    "latest, base, span",
    [
        (500, 50, 30),     # starting audience too small to trust
        (1400, 1000, 3),   # not enough history
        (1030, 1000, 30),  # gain too small
        (900, 1000, 30),   # decline earns nothing
    ],
)
def test_growth_is_ignored_when_the_numbers_cannot_be_trusted(latest, base, span):
    ev = run(listeners_latest=latest, listeners_base=base, span_days=span)
    assert "growth" not in names(ev)


@pytest.mark.parametrize("days, points", [(10, 25), (60, 15), (120, 5), (200, None)])
def test_new_release_points_fade_with_age(days, points):
    ev = run(last_release_date=days_ago(days))
    assert [c.points for c in ev.components if c.name == "new_release"] == (
        [] if points is None else [points]
    )


def test_announced_releases_do_not_count_as_new():
    ev = run(last_release_date=TODAY + timedelta(days=5))
    assert "new_release" not in names(ev)


@pytest.mark.parametrize("listeners, ok", [(300_000, True), (300_001, False)])
def test_audience_ceiling(listeners, ok):
    ev = run(last_release_date=days_ago(10), listeners_latest=listeners)
    assert check(ev, "audience_size").passed is ok
    assert ev.eligible is ok


@pytest.mark.parametrize("debut, ok", [(2021, True), (2020, False)])
def test_career_stage_limit(debut, ok):
    ev = run(last_release_date=days_ago(10), debut_year=debut)
    assert check(ev, "career_stage").passed is ok
    assert ev.eligible is ok


def test_missing_audience_and_debut_data_are_not_held_against_an_artist():
    ev = run(last_release_date=days_ago(10))
    assert ev.eligible
    assert check(ev, "audience_size").passed and check(ev, "career_stage").passed


@pytest.mark.parametrize("release", [days_ago(800), None])
def test_artists_with_no_recent_activity_are_not_eligible(release):
    ev = run(last_release_date=release)
    assert not check(ev, "recent_activity").passed
    assert not ev.eligible


def test_artists_without_public_releases_are_not_eligible():
    ev = run(has_public_content=False, last_release_date=days_ago(10))
    assert not check(ev, "has_content").passed
    assert not ev.eligible


def test_editorial_exclusion_always_wins():
    ev = run(last_release_date=days_ago(10), entry_status="excluded")
    assert not ev.eligible and not ev.appears
    assert not check(ev, "editorial_exclusion").passed


def test_an_editors_pick_overrides_failed_checks_and_explains_itself():
    ev = run(listeners_latest=2_000_000, entry_status="pick", entry_note="Rising fast in Lagos")

    assert ev.eligible and ev.appears and ev.editors_pick and ev.overridden
    assert not check(ev, "audience_size").passed
    pick = [c for c in ev.components if c.name == "editors_pick"][0]
    assert (pick.points, pick.detail) == (30, "Rising fast in Lagos")
    assert ev.note == "Rising fast in Lagos"


def test_a_pick_cannot_resurrect_an_archived_artist():
    ev = run(archived=True, entry_status="pick", last_release_date=days_ago(10))
    assert not ev.eligible and not ev.appears
    assert not check(ev, "active_artist").passed


@pytest.mark.parametrize("days, appears", [(120, False), (60, True)])
def test_artists_need_enough_points_to_appear(days, appears):
    ev = run(last_release_date=days_ago(days))
    assert ev.eligible
    assert ev.appears is appears


def test_ranking_prefers_score_then_picks_then_name():
    def item(artist_id, name, score, pick=False):
        facts = make_facts(artist_id=artist_id, name=name)
        evaluation = evaluate(facts, DEFAULT_RULES, TODAY)
        evaluation.score = score
        evaluation.editors_pick = pick
        return facts, evaluation

    items = [item(1, "Zed", 50), item(2, "Amy", 50), item(3, "Bob", 50, pick=True), item(4, "Cat", 80)]
    ordered = sorted(items, key=lambda pair: rank_key(*pair))
    assert [facts.name for facts, _ in ordered] == ["Cat", "Bob", "Amy", "Zed"]