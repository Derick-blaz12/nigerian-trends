import logging

import sqlalchemy as sa

from app.collectors import sync as musicbrainz
from app.collectors.http import BudgetExceeded, CollectorError
from app.collectors.runs import Counters, finish_run, start_run
from app.extensions import db
from app.models import Artist, ArtistExternalId, DataSource, MetricSnapshot
from app.models.mixins import utcnow
from app.services import metric_service

logger = logging.getLogger(__name__)

SOURCE_NAME = "Last.fm"
JOB = "lastfm"
LISTENERS = "lastfm_listeners"
PLAYCOUNT = "lastfm_playcount"
MAX_CONSECUTIVE_FAILURES = 3


def ensure_source(session=None):
    session = session or db.session
    source = session.scalar(sa.select(DataSource).where(DataSource.name == SOURCE_NAME))
    if source is None:
        source = DataSource(
            name=SOURCE_NAME,
            base_url="https://ws.audioscrobbler.com/2.0/",
            terms_url="https://www.last.fm/api/tos",
            allows_commercial_use=False,
            notes=(
                "Listener and play counts per artist, looked up by MusicBrainz id. "
                "Non-commercial use only unless a commercial agreement is made with Last.fm."
            ),
        )
        session.add(source)
        session.commit()
    return source


def _artists_to_measure(source, limit, session):
    """Active artists linked to MusicBrainz that have no listener snapshot yet today (UTC)."""
    mb_source = musicbrainz.ensure_source(session)
    day_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    measured = sa.select(MetricSnapshot.artist_id).where(
        MetricSnapshot.data_source_id == source.id,
        MetricSnapshot.metric_type == LISTENERS,
        MetricSnapshot.captured_at >= day_start,
    )
    return session.execute(
        sa.select(ArtistExternalId.artist_id, ArtistExternalId.external_id)
        .join(Artist, Artist.id == ArtistExternalId.artist_id)
        .where(
            ArtistExternalId.data_source_id == mb_source.id,
            Artist.archived_at.is_(None),
            ArtistExternalId.artist_id.not_in(measured),
        )
        .order_by(ArtistExternalId.artist_id)
        .limit(limit)
    ).all()


def run_lastfm(client, limit=200, triggered_by="cli", session=None):
    session = session or db.session
    source = ensure_source(session)
    run = start_run(source, JOB, triggered_by, session)
    counters = Counters()
    status, note = "succeeded", None
    failures = 0
    try:
        for artist_id, mbid in _artists_to_measure(source, limit, session):
            counters.seen += 1
            try:
                stats = client.get_artist_stats(mbid)
            except BudgetExceeded:
                raise
            except CollectorError as err:
                counters.error(f"{mbid}: {err}")
                failures += 1
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    raise CollectorError("Stopping: too many consecutive failures.") from err
                continue
            failures = 0

            if stats is None:  # Last.fm doesn't know this artist (yet)
                counters.skipped += 1
                continue
            for metric, value in ((LISTENERS, stats["listeners"]), (PLAYCOUNT, stats["playcount"])):
                if value is None:
                    continue
                snapshot = metric_service.record_snapshot(
                    artist_id, source.id, metric, value, session=session
                )
                if snapshot is not None:
                    counters.created += 1
        if counters.failed:
            status = "partial"
    except BudgetExceeded:
        status, note = "partial", "Stopped early: the request budget for this run was used up."
    except CollectorError as err:
        status = "partial" if counters.created else "failed"
        note = str(err)
    except Exception as err:  # anything unexpected is still recorded
        session.rollback()
        logger.exception("Unexpected error in the %s job", JOB)
        status, note = "failed", f"Unexpected error: {err.__class__.__name__}"
    finish_run(run, status, counters, client.requests_made, note, session)
    return run