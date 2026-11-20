from datetime import timedelta

import pytest
import sqlalchemy as sa

from app.collectors import lastfm_sync
from app.errors import ConflictError, NotFoundError, ValidationError
from app.extensions import db
from app.models import RadarEntry
from app.models.mixins import utcnow
from app.services import (
    album_service,
    artist_service,
    genre_service,
    metric_service,
    radar_service,
    song_service,
    update_service,
)


def today():
    return utcnow().date()


def make_artist(name, **extra):
    return artist_service.create_artist({"name": name, **extra})


def add_album(artist, days_ago, title="Debut EP"):
    return album_service.create_album(
        {
            "artist_id": artist.id,
            "title": title,
            "album_type": "ep",
            "release_date": (today() - timedelta(days=days_ago)).isoformat(),
        }
    )


def snapshot(artist, source, value, days_ago=0):
    return metric_service.record_snapshot(
        artist.id, source.id, "lastfm_listeners", value,
        captured_at=utcnow() - timedelta(days=days_ago),
    )


def names_on_radar(limit=50, **kwargs):
    items, _ = radar_service.build_radar(limit, **kwargs)
    return [artist.name for artist, _, _ in items]


def test_the_radar_is_empty_when_there_is_nothing_to_show(app):
    assert radar_service.build_radar(10) == ([], 0)


def test_an_artist_with_a_recent_release_appears_with_a_reason(app):
    add_album(make_artist("Tems"), 20)

    items, total = radar_service.build_radar(10)

    assert total == 1
    artist, _facts, evaluation = items[0]
    assert artist.name == "Tems"
    assert [c.name for c in evaluation.components] == ["new_release"]
    assert evaluation.score == 25


def test_old_catalogues_without_activity_stay_off(app):
    add_album(make_artist("Old Act"), 800)
    assert names_on_radar() == []


def test_audience_growth_from_snapshots_earns_points(app):
    tems = make_artist("Tems")
    add_album(tems, 400)
    source = lastfm_sync.ensure_source()
    snapshot(tems, source, 1000, days_ago=29)
    snapshot(tems, source, 1400, days_ago=0)

    items, _ = radar_service.build_radar(10)

    _artist, facts, evaluation = items[0]
    assert facts.span_days == 29
    assert evaluation.score == 20
    assert evaluation.components[0].detail == "Last.fm listeners up 40% in 29 days (1,000 to 1,400)."


def test_stale_audience_data_is_ignored(app):
    tems = make_artist("Tems")
    add_album(tems, 20)
    snapshot(tems, lastfm_sync.ensure_source(), 1_000_000, days_ago=20)

    items, _ = radar_service.build_radar(10)

    _artist, facts, evaluation = items[0]
    assert facts.listeners_latest is None
    assert [c.name for c in evaluation.components] == ["new_release"]


def test_a_large_audience_is_not_emerging(app):
    tems = make_artist("Tems")
    add_album(tems, 20)
    snapshot(tems, lastfm_sync.ensure_source(), 500_000)
    assert names_on_radar() == []


def test_commercial_mode_ignores_sources_without_a_commercial_licence(app):
    tems = make_artist("Tems")
    add_album(tems, 20)
    source = lastfm_sync.ensure_source()
    snapshot(tems, source, 500_000)
    assert names_on_radar() == []

    app.config["PLATFORM_COMMERCIAL"] = True
    assert names_on_radar() == ["Tems"]  # the Last.fm number is no longer used

    source.allows_commercial_use = True
    db.session.commit()
    assert names_on_radar() == []  # cleared for commercial use, so the number counts again


def test_archived_artists_and_releases_do_not_count(app):
    gone = make_artist("Gone")
    add_album(gone, 10)
    artist_service.archive_artist(gone)
    hidden = make_artist("Hidden")
    album_service.archive_album(add_album(hidden, 10))

    assert names_on_radar() == []


def test_songs_count_as_content_and_activity(app):
    tems = make_artist("Tems")
    song_service.create_song(
        {
            "title": "Free Mind",
            "release_date": (today() - timedelta(days=10)).isoformat(),
            "artists": [{"artist_id": tems.id, "role": "primary"}],
        }
    )

    items, _ = radar_service.build_radar(10)

    assert [c.detail for c in items[0][2].components] == ["New release 10 days ago."]


def test_recent_news_coverage_earns_points(app):
    tems = make_artist("Tems")
    add_album(tems, 400)
    update = update_service.create_update(
        {"artist_id": tems.id, "title": "Big news", "body": "A long enough announcement body for publishing."}
    )
    update_service.publish_update(update)

    items, _ = radar_service.build_radar(10)

    assert [c.name for c in items[0][2].components] == ["news_coverage"]
    assert items[0][2].score == 10


def test_editors_picks_appear_until_they_expire(app):
    tems = make_artist("Tems")
    assert names_on_radar() == []

    entry = radar_service.set_entry(
        tems, "pick", note="One to watch", expires_on=(today() + timedelta(days=7)).isoformat()
    )
    items, _ = radar_service.build_radar(10)
    assert items[0][2].editors_pick
    assert [c.detail for c in items[0][2].components] == ["One to watch"]

    entry.expires_at = utcnow() - timedelta(days=1)
    db.session.commit()
    assert names_on_radar() == []


def test_excluded_artists_stay_off_until_cleared(app):
    tems = make_artist("Tems")
    add_album(tems, 20)
    radar_service.set_entry(tems, "excluded", note="Already established")
    assert names_on_radar() == []

    assert radar_service.clear_entry(tems) is True
    assert names_on_radar() == ["Tems"]
    assert radar_service.clear_entry(tems) is False


def test_genre_filter(app):
    genre_service.create_genre("Afrobeats")
    genre_service.create_genre("Highlife")
    add_album(make_artist("Afro Act", genres=["afrobeats"]), 10, "One")
    add_album(make_artist("High Act", genres=["highlife"]), 10, "Two")

    assert sorted(names_on_radar()) == ["Afro Act", "High Act"]
    assert names_on_radar(genre="highlife") == ["High Act"]
    assert names_on_radar(genre="unknown") == []


def test_ranking_orders_by_score_and_the_limit_keeps_the_total(app):
    for name, days in [("Fresh", 5), ("Fresher", 10), ("Recent", 60)]:
        add_album(make_artist(name), days)

    items, total = radar_service.build_radar(2)

    assert [artist.name for artist, _, _ in items] == ["Fresh", "Fresher"]
    assert total == 3


def test_entry_validation(app):
    tems = make_artist("Tems")
    future = (today() + timedelta(days=3)).isoformat()
    past = (today() - timedelta(days=3)).isoformat()
    bad = [
        {"status": "featured"},
        {"status": "pick", "note": "n" * 201},
        {"status": "excluded", "expires_on": future},
        {"status": "pick", "expires_on": past},
        {"status": "pick", "expires_on": "soon"},
    ]
    for kwargs in bad:
        with pytest.raises(ValidationError):
            radar_service.set_entry(tems, **kwargs)

    gone = make_artist("Gone")
    artist_service.archive_artist(gone)
    with pytest.raises(ConflictError):
        radar_service.set_entry(gone, "pick")


def test_setting_an_entry_twice_updates_the_same_row(app):
    tems = make_artist("Tems")
    radar_service.set_entry(tems, "pick", note="First")
    radar_service.set_entry(tems, "excluded")

    entries = db.session.scalars(sa.select(RadarEntry)).all()
    assert [(e.status, e.note) for e in entries] == [("excluded", None)]


def test_explaining_an_unknown_artist_is_a_404(app):
    with pytest.raises(NotFoundError):
        radar_service.explain(999999)