import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.errors import ConflictError, NotFoundError, ValidationError
from app.extensions import db
from app.models import Album, Artist, Song, SongArtist
from app.models.mixins import utcnow
from app.utils.catalogue import escape_like, parse_release_date, title_key
from app.utils.validation import clean_string

ALBUM_TYPES = ("album", "ep", "single", "mixtape")
STATUSES = ("active", "archived", "all")
MAX_SEARCH_LENGTH = 100


def _reject_unknown_fields(data, allowed):
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object.")
    unknown = [key for key in data if key not in allowed]
    if unknown:
        raise ValidationError("Unknown fields.", details={k: "Unknown field." for k in unknown})


def _validate_fields(data):
    changes = {}
    if "title" in data:
        changes["title"] = clean_string(data["title"], "title", min_len=1, max_len=200)
    if "album_type" in data:
        if data["album_type"] not in ALBUM_TYPES:
            raise ValidationError(
                "album_type is invalid.",
                details={"album_type": "Must be one of: album, ep, single, mixtape."},
            )
        changes["album_type"] = data["album_type"]
    if "release_date" in data:
        changes["release_date"] = parse_release_date(data["release_date"])
    return changes


def _ensure_title_available(artist_id, title, session, exclude_id=None):
    stmt = sa.select(Album).where(Album.artist_id == artist_id)
    if exclude_id is not None:
        stmt = stmt.where(Album.id != exclude_id)
    key = title_key(title)
    for other in session.scalars(stmt):
        if title_key(other.title) == key:
            note = " (archived)" if other.archived_at else ""
            raise ConflictError(
                "This artist already has an album with this title.",
                details={"title": f"Matches '{other.title}'{note}, id {other.id}."},
            )


def _load_options():
    return (
        selectinload(Album.artist),
        selectinload(Album.songs).selectinload(Song.credits).selectinload(SongArtist.artist),
    )


def get_album(album_id, include_hidden=False, session=None):
    session = session or db.session
    album = session.scalar(sa.select(Album).where(Album.id == album_id).options(*_load_options()))
    if album is None or (not include_hidden and not album.is_public):
        raise NotFoundError("Album not found.")
    return album


def list_albums(page, per_page, q=None, artist_id=None, status="active", session=None):
    """Admin listing."""
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

    stmt = sa.select(Album)
    if status == "active":
        stmt = stmt.where(Album.archived_at.is_(None))
    elif status == "archived":
        stmt = stmt.where(Album.archived_at.is_not(None))
    if artist_id is not None:
        stmt = stmt.where(Album.artist_id == artist_id)
    if q:
        stmt = stmt.where(Album.title.ilike(f"%{escape_like(q)}%", escape="\\"))

    total = session.scalar(sa.select(sa.func.count()).select_from(stmt.subquery()))
    items = session.scalars(
        stmt.options(selectinload(Album.artist))
        .order_by(Album.release_date.desc().nulls_last(), Album.id.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()
    return items, total


def search_albums(q, limit, session=None):
    """Public search: matches the album title or its artist's name."""
    session = session or db.session
    escaped = escape_like(q)
    title_match = Album.title.ilike(f"%{escaped}%", escape="\\")
    artist_match = Album.artist.has(Artist.name.ilike(f"%{escaped}%", escape="\\"))
    stmt = sa.select(Album).where(
        Album.archived_at.is_(None),
        Album.artist.has(Artist.archived_at.is_(None)),
        sa.or_(title_match, artist_match),
    )
    rank = sa.case(
        (Album.title.ilike(f"{escaped}%", escape="\\"), 0), (title_match, 1), else_=2
    )
    total = session.scalar(sa.select(sa.func.count()).select_from(stmt.subquery()))
    items = session.scalars(
        stmt.options(selectinload(Album.artist))
        .order_by(rank, Album.release_date.desc().nulls_last(), Album.id.desc())
        .limit(limit)
    ).all()
    return items, total


def create_album(data, session=None):
    session = session or db.session
    _reject_unknown_fields(data, ("artist_id", "title", "album_type", "release_date"))
    missing = [f for f in ("artist_id", "title") if data.get(f) in (None, "")]
    if missing:
        raise ValidationError(
            "Missing required fields.", details={f: "This field is required." for f in missing}
        )

    artist_id = data["artist_id"]
    if isinstance(artist_id, bool) or not isinstance(artist_id, int):
        raise ValidationError("artist_id is invalid.", details={"artist_id": "Must be a whole number."})
    artist = session.get(Artist, artist_id)
    if artist is None or artist.archived_at is not None:
        raise ValidationError(
            "artist_id is invalid.", details={"artist_id": "No active artist has this id."}
        )

    changes = _validate_fields(data)
    _ensure_title_available(artist.id, changes["title"], session)

    album = Album(artist_id=artist.id, **changes)
    session.add(album)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ConflictError("This artist already has an album with this title.") from None
    return get_album(album.id, include_hidden=True, session=session)


def update_album(album, data, session=None):
    session = session or db.session
    if isinstance(data, dict) and "artist_id" in data:
        raise ValidationError(
            "artist_id cannot be changed.", details={"artist_id": "Create a new album instead."}
        )
    _reject_unknown_fields(data, ("title", "album_type", "release_date"))
    if not data:
        raise ValidationError("Provide at least one field to update.")

    changes = _validate_fields(data)
    if "title" in changes:
        _ensure_title_available(album.artist_id, changes["title"], session, exclude_id=album.id)
    for field, value in changes.items():
        setattr(album, field, value)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ConflictError("This artist already has an album with this title.") from None
    return get_album(album.id, include_hidden=True, session=session)


def archive_album(album, session=None):
    session = session or db.session
    if album.archived_at is None:
        album.archived_at = utcnow()
        session.commit()
    return get_album(album.id, include_hidden=True, session=session)


def restore_album(album, session=None):
    session = session or db.session
    if album.archived_at is not None:
        album.archived_at = None
        session.commit()
    return get_album(album.id, include_hidden=True, session=session)