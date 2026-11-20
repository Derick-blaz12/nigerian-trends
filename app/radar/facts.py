from collections import defaultdict
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import (
    Album,
    Artist,
    ArtistUpdate,
    DataSource,
    Genre,
    MetricSnapshot,
    RadarEntry,
    Song,
    SongArtist,
)
from app.models.mixins import utcnow
from app.radar.engine import ArtistFacts


def allowed_source_ids(commercial, session):
    stmt = sa.select(DataSource.id).where(DataSource.is_active.is_(True))
    if commercial:
        stmt = stmt.where(DataSource.allows_commercial_use.is_(True))
    return list(session.scalars(stmt))


def _apply_metrics(facts, series, rules, now):
    if not series:
        return
    latest_value, latest_at = series[-1]
    if (now - latest_at).days > rules.metric_max_age_days:
        return  # too old to say anything about the audience today
    facts.listeners_latest = latest_value
    window_start = latest_at - timedelta(days=rules.growth_window_days)
    for value, captured_at in series:
        if captured_at >= window_start:
            facts.listeners_base = value
            facts.span_days = (latest_at - captured_at).days
            break


def load_facts(rules, commercial, today, session=None, artist_ids=None, genre=None,
               include_archived=False):
    """Gather the facts for many artists with a handful of queries. Returns [(artist, facts)]."""
    session = session or db.session
    now = utcnow()

    stmt = sa.select(Artist).options(selectinload(Artist.genres))
    if not include_archived:
        stmt = stmt.where(Artist.archived_at.is_(None))
    if artist_ids is not None:
        stmt = stmt.where(Artist.id.in_(artist_ids))
    genre = (genre or "").strip().lower()
    if genre:
        stmt = stmt.where(Artist.genres.any(Genre.slug == genre))
    artists = session.scalars(stmt.order_by(Artist.id)).all()
    if not artists:
        return []
    ids = [artist.id for artist in artists]

    # Public content and the most recent release (albums and songs)
    has_content = set(
        session.scalars(
            sa.select(Album.artist_id).where(Album.archived_at.is_(None), Album.artist_id.in_(ids))
        )
    )
    primary_song = sa.and_(
        SongArtist.role == "primary", SongArtist.artist_id.in_(ids), Song.archived_at.is_(None)
    )
    has_content |= set(
        session.scalars(
            sa.select(SongArtist.artist_id)
            .join(Song, Song.id == SongArtist.song_id)
            .where(primary_song)
        )
    )

    last_release = {}
    album_dates = session.execute(
        sa.select(Album.artist_id, sa.func.max(Album.release_date))
        .where(
            Album.archived_at.is_(None),
            Album.release_date.is_not(None),
            Album.release_date <= today,
            Album.artist_id.in_(ids),
        )
        .group_by(Album.artist_id)
    )
    for artist_id, released in album_dates:
        last_release[artist_id] = released
    song_dates = session.execute(
        sa.select(SongArtist.artist_id, sa.func.max(Song.release_date))
        .join(Song, Song.id == SongArtist.song_id)
        .where(primary_song, Song.release_date.is_not(None), Song.release_date <= today)
        .group_by(SongArtist.artist_id)
    )
    for artist_id, released in song_dates:
        if artist_id not in last_release or released > last_release[artist_id]:
            last_release[artist_id] = released

    last_update = {
        artist_id: published
        for artist_id, published in session.execute(
            sa.select(ArtistUpdate.artist_id, sa.func.max(ArtistUpdate.published_at))
            .where(ArtistUpdate.status == "published", ArtistUpdate.artist_id.in_(ids))
            .group_by(ArtistUpdate.artist_id)
        )
    }

    # Audience snapshots, only from sources we're allowed to use right now
    series = defaultdict(list)
    source_ids = allowed_source_ids(commercial, session)
    if source_ids:
        since = now - timedelta(days=max(rules.growth_window_days, rules.metric_max_age_days))
        rows = session.execute(
            sa.select(MetricSnapshot.artist_id, MetricSnapshot.value, MetricSnapshot.captured_at)
            .where(
                MetricSnapshot.metric_type == rules.metric,
                MetricSnapshot.data_source_id.in_(source_ids),
                MetricSnapshot.artist_id.in_(ids),
                MetricSnapshot.captured_at >= since,
            )
            .order_by(MetricSnapshot.artist_id, MetricSnapshot.captured_at)
        )
        for artist_id, value, captured_at in rows:
            series[artist_id].append((value, captured_at))

    # Editorial decisions (an expired pick counts as no decision)
    entries = {}
    for entry in session.scalars(sa.select(RadarEntry).where(RadarEntry.artist_id.in_(ids))):
        if entry.status == "pick" and entry.expires_at is not None and entry.expires_at <= now:
            continue
        entries[entry.artist_id] = entry

    pairs = []
    for artist in artists:
        facts = ArtistFacts(
            artist_id=artist.id,
            name=artist.name,
            archived=artist.archived_at is not None,
            debut_year=artist.debut_year,
            has_public_content=artist.id in has_content,
            last_release_date=last_release.get(artist.id),
            last_update_at=last_update.get(artist.id),
        )
        _apply_metrics(facts, series.get(artist.id), rules, now)
        entry = entries.get(artist.id)
        if entry is not None:
            facts.entry_status, facts.entry_note = entry.status, entry.note
        pairs.append((artist, facts))
    return pairs