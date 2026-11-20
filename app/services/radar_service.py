from datetime import datetime, time, timedelta, timezone

import sqlalchemy as sa
from flask import current_app

from app.errors import ConflictError, NotFoundError, ValidationError
from app.extensions import db
from app.models import Artist, RadarEntry
from app.models.mixins import utcnow
from app.radar import facts as facts_module
from app.radar.engine import evaluate, rank_key
from app.radar.rules import DEFAULT_RULES
from app.utils.catalogue import parse_release_date
from app.utils.validation import clean_string

ENTRY_STATUSES = ("pick", "excluded")
MAX_NOTE = 200


def _today():
    return utcnow().date()


def build_radar(limit, genre=None, session=None, rules=DEFAULT_RULES):
    """Returns ([(artist, facts, evaluation)] best first, total number on the Radar)."""
    session = session or db.session
    today = _today()
    pairs = facts_module.load_facts(
        rules, current_app.config["PLATFORM_COMMERCIAL"], today, session=session, genre=genre
    )
    evaluated = [(artist, facts, evaluate(facts, rules, today)) for artist, facts in pairs]
    appearing = [item for item in evaluated if item[2].appears]
    appearing.sort(key=lambda item: rank_key(item[1], item[2]))
    return appearing[:limit], len(appearing)


def explain(artist_id, session=None, rules=DEFAULT_RULES):
    """Why is (or isn't) this artist on the Radar? Works for any artist, archived included."""
    session = session or db.session
    today = _today()
    pairs = facts_module.load_facts(
        rules, current_app.config["PLATFORM_COMMERCIAL"], today, session=session,
        artist_ids=[artist_id], include_archived=True,
    )
    if not pairs:
        raise NotFoundError("Artist not found.")
    artist, facts = pairs[0]
    return artist, facts, evaluate(facts, rules, today)


def _parse_expiry(value, status):
    if value in (None, ""):
        return None
    if status != "pick":
        raise ValidationError(
            "expires_on is invalid.", details={"expires_on": "Only picks can expire."}
        )
    day = parse_release_date(value, "expires_on")
    if day < _today():
        raise ValidationError(
            "expires_on is invalid.", details={"expires_on": "Must be today or later."}
        )
    # A pick lasts until the end of that day (UTC).
    return datetime.combine(day + timedelta(days=1), time.min, tzinfo=timezone.utc)


def set_entry(artist, status, note=None, expires_on=None, user_id=None, session=None):
    session = session or db.session
    if status not in ENTRY_STATUSES:
        raise ValidationError("status is invalid.", details={"status": "Must be one of: pick, excluded."})
    if artist.archived_at is not None:
        raise ConflictError("The artist is archived.")
    note = None if note in (None, "") else clean_string(note, "note", min_len=1, max_len=MAX_NOTE)
    expires_at = _parse_expiry(expires_on, status)

    entry = session.scalar(sa.select(RadarEntry).where(RadarEntry.artist_id == artist.id))
    if entry is None:
        entry = RadarEntry(artist_id=artist.id, created_by=user_id)
        session.add(entry)
    entry.status, entry.note, entry.expires_at = status, note, expires_at
    session.commit()
    return entry


def clear_entry(artist, session=None):
    session = session or db.session
    entry = session.scalar(sa.select(RadarEntry).where(RadarEntry.artist_id == artist.id))
    if entry is None:
        return False
    session.delete(entry)
    session.commit()
    return True


def list_entries(status, page, per_page, session=None):
    session = session or db.session
    if status in (None, ""):
        status = None
    elif status not in ENTRY_STATUSES:
        raise ValidationError("status is invalid.", details={"status": "Must be one of: pick, excluded."})
    count_stmt = sa.select(sa.func.count()).select_from(RadarEntry)
    stmt = sa.select(RadarEntry, Artist).join(Artist, Artist.id == RadarEntry.artist_id)
    if status:
        count_stmt = count_stmt.where(RadarEntry.status == status)
        stmt = stmt.where(RadarEntry.status == status)
    total = session.scalar(count_stmt)
    rows = session.execute(
        stmt.order_by(RadarEntry.updated_at.desc(), RadarEntry.id.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()
    return rows, total