import secrets
from datetime import date

import sqlalchemy as sa
from flask import current_app
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.errors import AppError, ConflictError, NotFoundError, ValidationError
from app.extensions import db
from app.models import Artist, Genre, Song, SongArtist
from app.models.mixins import utcnow
from app.storage import get_storage
from app.utils.images import process_image
from app.utils.validation import clean_string, slugify
from app.services.genre_service import load_genres

EDITABLE_FIELDS = ("name", "bio", "origin_city", "debut_year", "genres")
STATUSES = ("active", "archived", "all")
MAX_BIO_LENGTH = 5000
MAX_SEARCH_LENGTH = 100


# ---------- validation helpers ----------

def _reject_unknown_fields(data):
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object.")
    unknown = [key for key in data if key not in EDITABLE_FIELDS]
    if unknown:
        raise ValidationError("Unknown fields.", details={k: "Unknown field." for k in unknown})


def _optional_text(value, field, max_len):
    if value is None:
        return None
    return clean_string(value, field, min_len=0, max_len=max_len) or None


def _debut_year(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("debut_year is invalid.", details={"debut_year": "Must be a whole number."})
    latest = date.today().year + 1
    if not 1950 <= value <= latest:
        raise ValidationError(
            "debut_year is invalid.", details={"debut_year": f"Must be between 1950 and {latest}."}
        )
    return value


def _ensure_name_available(name, session, exclude_id=None):
    stmt = sa.select(Artist.id).where(sa.func.lower(Artist.name) == sa.func.lower(name))
    if exclude_id is not None:
        stmt = stmt.where(Artist.id != exclude_id)
    if session.scalar(stmt) is not None:
        raise ConflictError(
            "An artist with this name already exists.", details={"name": "Already exists."}
        )


def _validate(data, session, exclude_id=None):
    """Validate every field first, so a bad request changes nothing."""
    _reject_unknown_fields(data)
    changes = {}
    if "name" in data:
        name = clean_string(data["name"], "name", min_len=1, max_len=200)
        _ensure_name_available(name, session, exclude_id)
        changes["name"] = name
    if "bio" in data:
        changes["bio"] = _optional_text(data["bio"], "bio", MAX_BIO_LENGTH)
    if "origin_city" in data:
        changes["origin_city"] = _optional_text(data["origin_city"], "origin_city", 100)
    if "debut_year" in data:
        changes["debut_year"] = _debut_year(data["debut_year"])
    if "genres" in data:
        changes["genres"] = load_genres(data["genres"], session)
    return changes


def _unique_slug(name, session):
    base = slugify(name)[:200].strip("-") or "artist"
    taken = set(session.scalars(sa.select(Artist.slug).where(Artist.slug.like(f"{base}%"))))
    if base not in taken:
        return base
    number = 2
    while f"{base}-{number}" in taken:
        number += 1
    return f"{base}-{number}"


def _escape_like(text):
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _detail_options():
    return (
        selectinload(Artist.genres),
        selectinload(Artist.albums),
        selectinload(Artist.song_credits)
        .selectinload(SongArtist.song)
        .selectinload(Song.credits)
        .selectinload(SongArtist.artist),
    )


# ---------- reading ----------

def list_artists(page, per_page, q=None, genre=None, status="active", session=None):
    session = session or db.session
    if status not in STATUSES:
        raise ValidationError(
            "status is invalid.", details={"status": "Must be one of: active, archived, all."}
        )
    q = (q or "").strip()
    if len(q) > MAX_SEARCH_LENGTH:
        raise ValidationError(
            "q is invalid.", details={"q": f"Must be at most {MAX_SEARCH_LENGTH} characters."}
        )
    genre = (genre or "").strip().lower()

    stmt = sa.select(Artist)
    if status == "active":
        stmt = stmt.where(Artist.archived_at.is_(None))
    elif status == "archived":
        stmt = stmt.where(Artist.archived_at.is_not(None))
    if genre:
        stmt = stmt.where(Artist.genres.any(Genre.slug == genre))

    order = [sa.func.lower(Artist.name), Artist.id]
    if q:
        escaped = _escape_like(q)
        stmt = stmt.where(Artist.name.ilike(f"%{escaped}%", escape="\\"))
        starts_with = sa.case((Artist.name.ilike(f"{escaped}%", escape="\\"), 0), else_=1)
        order = [starts_with, *order]

    total = session.scalar(sa.select(sa.func.count()).select_from(stmt.subquery()))
    items = session.scalars(
        stmt.options(selectinload(Artist.genres))
        .order_by(*order)
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()
    return items, total


def get_artist_by_slug(slug, include_archived=False, session=None):
    session = session or db.session
    stmt = sa.select(Artist).where(Artist.slug == slug).options(*_detail_options())
    if not include_archived:
        stmt = stmt.where(Artist.archived_at.is_(None))
    artist = session.scalar(stmt)
    if artist is None:
        raise NotFoundError("Artist not found.")
    return artist


def get_artist_by_id(artist_id, session=None):
    session = session or db.session
    artist = session.scalar(
        sa.select(Artist).where(Artist.id == artist_id).options(*_detail_options())
    )
    if artist is None:
        raise NotFoundError("Artist not found.")
    return artist


# ---------- writing ----------

def create_artist(data, session=None):
    session = session or db.session
    changes = _validate(data, session)
    if "name" not in changes:
        raise ValidationError("name is required.", details={"name": "This field is required."})

    artist = Artist(slug=_unique_slug(changes["name"], session), **changes)
    session.add(artist)
    try:
        session.commit()
    except IntegrityError:  # two admins created the same name at the same instant
        session.rollback()
        raise ConflictError("An artist with this name already exists.") from None
    return get_artist_by_id(artist.id, session)


def update_artist(artist, data, session=None):
    session = session or db.session
    if not isinstance(data, dict) or not data:
        raise ValidationError("Provide at least one field to update.")
    changes = _validate(data, session, exclude_id=artist.id)
    for field, value in changes.items():
        setattr(artist, field, value)  # the slug is deliberately never changed
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ConflictError("An artist with this name already exists.") from None
    return get_artist_by_id(artist.id, session)


def archive_artist(artist, session=None):
    session = session or db.session
    if artist.archived_at is None:
        artist.archived_at = utcnow()
        session.commit()
    return get_artist_by_id(artist.id, session)


def restore_artist(artist, session=None):
    session = session or db.session
    if artist.archived_at is not None:
        artist.archived_at = None
        session.commit()
    return get_artist_by_id(artist.id, session)


# ---------- images ----------

def set_artist_image(artist, data, session=None):
    session = session or db.session
    max_bytes = current_app.config["MAX_IMAGE_BYTES"]
    if len(data) > max_bytes:
        raise AppError(
            "Image is too large.",
            status_code=413,
            code="payload_too_large",
            details={"image": f"Maximum size is {max_bytes // 1024} KB."},
        )

    jpeg = process_image(data)
    storage = get_storage()
    old_url = artist.image_url
    # An unguessable name also means a replaced image never hits a stale cache.
    new_url = storage.save(f"artists/{artist.id}-{secrets.token_hex(8)}.jpg", jpeg)
    artist.image_url = new_url
    try:
        session.commit()
    except Exception:
        session.rollback()
        storage.delete_url(new_url)
        raise
    storage.delete_url(old_url)
    return get_artist_by_id(artist.id, session)


def remove_artist_image(artist, session=None):
    session = session or db.session
    old_url = artist.image_url
    if old_url:
        artist.image_url = None
        session.commit()
        get_storage().delete_url(old_url)
    return get_artist_by_id(artist.id, session)