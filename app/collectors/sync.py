import logging
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.collectors.http import BudgetExceeded, CollectorError
from app.collectors.runs import Counters, finish_run, start_run
from app.errors import AppError
from app.extensions import db
from app.models import Album, Artist, ArtistExternalId, DataSource, MatchCandidate
from app.models.mixins import utcnow
from app.services import link_service, song_service
from app.utils.catalogue import title_key

logger = logging.getLogger(__name__)

SOURCE_NAME = "MusicBrainz"
JOB = "musicbrainz"
NO_MATCH_RETRY_DAYS = 30
MAX_CONSECUTIVE_FAILURES = 3
MAX_REVIEW_CANDIDATES = 3
MIN_NEAR_MATCH_SCORE = 80


def ensure_source(session=None):
    session = session or db.session
    source = session.scalar(sa.select(DataSource).where(DataSource.name == SOURCE_NAME))
    if source is None:
        source = DataSource(
            name=SOURCE_NAME,
            base_url="https://musicbrainz.org/ws/2",
            terms_url="https://musicbrainz.org/doc/MusicBrainz_API",
            notes=(
                "Core data is CC0. We use only core data (identity, release groups, official "
                "links). The web service is free for non-commercial use; commercial use needs a "
                "MetaBrainz plan. Max 1 request per second, with an identifying User-Agent."
            ),
        )
        session.add(source)
        session.commit()
    return source


def decide_match(name, hits):
    """Returns ('link', hit, []), ('review', None, candidates) or ('none', None, [])."""
    key = title_key(name)
    exact = [h for h in hits if title_key(h["name"]) == key]
    if len(exact) == 1 and exact[0]["country"] == "NG":
        return "link", exact[0], []
    if exact:
        return "review", None, exact[:MAX_REVIEW_CANDIDATES]
    near = [h for h in hits if h["country"] == "NG" and h["score"] >= MIN_NEAR_MATCH_SCORE]
    if near:
        return "review", None, near[:MAX_REVIEW_CANDIDATES]
    return "none", None, []


# ---------- stage 1: link our artists to MusicBrainz ----------

def _linkable_artists(source, limit, session):
    cutoff = utcnow() - timedelta(days=NO_MATCH_RETRY_DAYS)
    linked = sa.select(ArtistExternalId.artist_id).where(
        ArtistExternalId.data_source_id == source.id
    )
    blocked = sa.select(MatchCandidate.artist_id).where(
        MatchCandidate.data_source_id == source.id,
        sa.or_(
            MatchCandidate.status == "pending",
            sa.and_(MatchCandidate.status == "no_match", MatchCandidate.created_at > cutoff),
        ),
    )
    return session.scalars(
        sa.select(Artist)
        .where(Artist.archived_at.is_(None), Artist.id.not_in(linked), Artist.id.not_in(blocked))
        .order_by(Artist.id)
        .limit(limit)
    ).all()


def _clear_no_match(artist, source, session):
    session.execute(
        sa.delete(MatchCandidate).where(
            MatchCandidate.artist_id == artist.id,
            MatchCandidate.data_source_id == source.id,
            MatchCandidate.status == "no_match",
        )
    )


def _try_link(artist, source, mbid, session):
    _clear_no_match(artist, source, session)
    session.add(ArtistExternalId(artist_id=artist.id, data_source_id=source.id, external_id=mbid))
    try:
        session.commit()
    except IntegrityError:  # this MusicBrainz id already belongs to another of our artists
        session.rollback()
        return False
    return True


def _record_match(artist, source, hits, counters, session):
    rejected = set(
        session.scalars(
            sa.select(MatchCandidate.external_id).where(
                MatchCandidate.artist_id == artist.id,
                MatchCandidate.data_source_id == source.id,
                MatchCandidate.status == "rejected",
            )
        )
    )
    hits = [h for h in hits if h["mbid"] not in rejected]
    decision, chosen, candidates = decide_match(artist.name, hits)

    if decision == "link":
        if _try_link(artist, source, chosen["mbid"], session):
            counters.created += 1
            return
        decision, candidates = "review", [chosen]  # a human must untangle the duplicate

    _clear_no_match(artist, source, session)
    if decision == "review":
        for item in candidates:
            session.add(
                MatchCandidate(
                    artist_id=artist.id,
                    data_source_id=source.id,
                    external_id=item["mbid"],
                    external_name=item["name"],
                    country=item["country"],
                    disambiguation=item["disambiguation"],
                    begin_year=item["begin_year"],
                    score=item["score"],
                    status="pending",
                )
            )
    else:
        session.add(
            MatchCandidate(artist_id=artist.id, data_source_id=source.id, status="no_match")
        )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        counters.error(f"'{artist.name}': could not save match candidates.")
        return
    counters.skipped += 1


def link_artists(client, source, counters, limit, session=None):
    session = session or db.session
    failures = 0
    for artist in _linkable_artists(source, limit, session):
        counters.seen += 1
        name = artist.name
        try:
            hits = client.search_artists(name)
        except BudgetExceeded:
            raise
        except CollectorError as err:
            counters.error(f"search '{name}': {err}")
            failures += 1
            if failures >= MAX_CONSECUTIVE_FAILURES:
                raise CollectorError("Stopping: too many consecutive failures.") from err
            continue
        failures = 0
        _record_match(artist, source, hits, counters, session)


# ---------- stage 2: enrich linked artists ----------

def _enrich_one(client, link_id, artist_id, mbid, counters, session):
    artist = session.get(Artist, artist_id)
    link = session.get(ArtistExternalId, link_id)

    detail = client.get_artist(mbid)
    if detail is None:
        name = artist.name
        link.last_synced_at = utcnow()
        session.commit()
        counters.error(f"'{name}': MusicBrainz no longer has id {mbid}.")
        return

    for platform, url in detail["links"]:
        try:
            link_service.add_link(
                "artist", artist.id, {"platform": platform, "url": url}, session=session
            )
            counters.created += 1
        except AppError:  # already stored, in use elsewhere, or over the per-item limit
            counters.skipped += 1

    groups = client.browse_release_groups(mbid)
    singles = client.browse_singles(mbid)
    existing = {
        title_key(album.title): album
        for album in session.scalars(sa.select(Album).where(Album.artist_id == artist.id))
    }
    for group in groups:
        key = title_key(group["title"])
        album = existing.get(key)
        if album is None:
            album = Album(
                artist_id=artist.id,
                title=group["title"],
                album_type=group["album_type"],
                release_date=group["release_date"],
            )
            session.add(album)
            existing[key] = album
            counters.created += 1
        elif album.release_date is None and group["release_date"] is not None:
            album.release_date = group["release_date"]
            counters.updated += 1
        else:
            counters.skipped += 1
    session.commit()  # albums are saved before the songs, which are committed one by one

    for single in singles:
        data = {
            "title": single["title"],
            "artists": [{"artist_id": artist_id, "role": "primary"}],
        }
        if single["release_date"] is not None:
            data["release_date"] = single["release_date"].isoformat()
        try:
            song_service.create_song(data, session=session)
            counters.created += 1
        except AppError:  # a song like this already exists, or the title is unusable
            counters.skipped += 1

    years = [item["year"] for item in groups + singles if item["year"]]
    if artist.debut_year is None and years:
        artist.debut_year = min(years)  # inferred from the earliest release, never overwritten
        counters.updated += 1

    link.last_synced_at = utcnow()
    session.commit()


def enrich_artists(client, source, counters, limit, stale_days, session=None):
    session = session or db.session
    cutoff = utcnow() - timedelta(days=stale_days)
    links = session.scalars(
        sa.select(ArtistExternalId)
        .join(Artist, Artist.id == ArtistExternalId.artist_id)
        .where(
            ArtistExternalId.data_source_id == source.id,
            Artist.archived_at.is_(None),
            sa.or_(
                ArtistExternalId.last_synced_at.is_(None),
                ArtistExternalId.last_synced_at < cutoff,
            ),
        )
        .order_by(ArtistExternalId.last_synced_at.asc().nulls_first(), ArtistExternalId.id)
        .limit(limit)
    ).all()

    failures = 0
    for link in links:
        counters.seen += 1
        link_id, artist_id, mbid = link.id, link.artist_id, link.external_id
        try:
            _enrich_one(client, link_id, artist_id, mbid, counters, session)
            failures = 0
        except BudgetExceeded:
            session.rollback()
            raise
        except CollectorError as err:
            session.rollback()
            counters.error(f"{mbid}: {err}")
            failures += 1
            if failures >= MAX_CONSECUTIVE_FAILURES:
                raise CollectorError("Stopping: too many consecutive failures.") from err
        except IntegrityError:
            session.rollback()
            counters.error(f"{mbid}: could not save the imported data.")
            session.execute(
                sa.update(ArtistExternalId)
                .where(ArtistExternalId.id == link_id)
                .values(last_synced_at=utcnow())
            )
            session.commit()


# ---------- the job ----------

def run_musicbrainz(client, link=True, enrich=True, limit=25, stale_days=30,
                    triggered_by="cli", session=None):
    session = session or db.session
    source = ensure_source(session)
    run = start_run(source, JOB, triggered_by, session)
    counters = Counters()
    status, note = "succeeded", None
    try:
        if link:
            link_artists(client, source, counters, limit, session)
        if enrich:
            enrich_artists(client, source, counters, limit, stale_days, session)
        if counters.failed:
            status = "partial"
    except BudgetExceeded:
        status, note = "partial", "Stopped early: the request budget for this run was used up."
    except CollectorError as err:
        status = "partial" if (counters.created or counters.updated) else "failed"
        note = str(err)
    except Exception as err:  # anything unexpected is still recorded
        session.rollback()
        logger.exception("Unexpected error in the %s job", JOB)
        status, note = "failed", f"Unexpected error: {err.__class__.__name__}"
    finish_run(run, status, counters, client.requests_made, note, session)
    return run