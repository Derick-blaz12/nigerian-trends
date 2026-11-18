import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from app.errors import ConflictError, NotFoundError, ValidationError
from app.extensions import db
from app.models import Album, Artist, ArtistUpdate, Song, SongArtist
from app.models.mixins import utcnow
from app.utils.catalogue import escape_like, validate_https_url
from app.utils.validation import clean_string

CATEGORIES = ("news", "release", "interview", "event")
STATUSES = ("draft", "published", "archived", "all")
EDITABLE_FIELDS = (
    "title", "summary", "body", "category",
    "source_name", "source_url", "song_id", "album_id",
)
CREATE_FIELDS = ("artist_id", *EDITABLE_FIELDS)
MIN_PUBLISH_BODY = 20
MAX_BODY = 20000
MAX_SEARCH_LENGTH = 100
MAX_ID = 2_147_483_647


# ---------- validation ----------

def _optional_text(value, field, max_len):
    if value is None:
        return None
    return clean_string(value, field, min_len=0, max_len=max_len) or None


def _id(value, field):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_ID:
        raise ValidationError(f"{field} is invalid.", details={field: "Must be a whole number."})
    return value


def _validate(data, allowed):
    """Validate every field first, so a bad request changes nothing."""
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object.")
    unknown = [key for key in data if key not in allowed]
    if unknown:
        raise ValidationError("Unknown fields.", details={k: "Unknown field." for k in unknown})

    changes = {}
    if "artist_id" in data:
        changes["artist_id"] = _id(data["artist_id"], "artist_id")
    if "title" in data:
        changes["title"] = clean_string(data["title"], "title", min_len=3, max_len=200)
    if "summary" in data:
        changes["summary"] = _optional_text(data["summary"], "summary", 300)
    if "body" in data:
        changes["body"] = clean_string(data["body"], "body", min_len=0, max_len=MAX_BODY)
    if "category" in data:
        if data["category"] not in CATEGORIES:
            raise ValidationError(
                "category is invalid.",
                details={"category": "Must be one of: " + ", ".join(CATEGORIES) + "."},
            )
        changes["category"] = data["category"]
    if "source_name" in data:
        changes["source_name"] = _optional_text(data["source_name"], "source_name", 150)
    if "source_url" in data:
        raw = data["source_url"]
        changes["source_url"] = None if raw in (None, "") else validate_https_url(raw, "source_url")
    if "song_id" in data:
        changes["song_id"] = _id(data["song_id"], "song_id")
    if "album_id" in data:
        changes["album_id"] = _id(data["album_id"], "album_id")
    return changes


def _check_relations(artist_id, song_id, album_id, session):
    if song_id is not None:
        song = session.get(Song, song_id)
        if song is None:
            raise ValidationError("song_id is invalid.", details={"song_id": "No song has this id."})
        if song.archived_at is not None:
            raise ValidationError("song_id is invalid.", details={"song_id": "This song is archived."})
        if artist_id not in {credit.artist_id for credit in song.credits}:
            raise ValidationError(
                "song_id is invalid.", details={"song_id": "The artist must be credited on this song."}
            )
    if album_id is not None:
        album = session.get(Album, album_id)
        if album is None:
            raise ValidationError("album_id is invalid.", details={"album_id": "No album has this id."})
        if album.archived_at is not None:
            raise ValidationError("album_id is invalid.", details={"album_id": "This album is archived."})
        if album.artist_id != artist_id:
            raise ValidationError(
                "album_id is invalid.", details={"album_id": "The album must belong to this artist."}
            )


def _check_source(name, url):
    if url and not name:
        raise ValidationError(
            "source_name is required.",
            details={"source_name": "Add the name of the source when you link to it."},
        )


def _check_publishable(title, body, artist):
    problems = {}
    if artist.archived_at is not None:
        problems["artist_id"] = "The artist is archived."
    if len(body) < MIN_PUBLISH_BODY:
        problems["body"] = f"Write at least {MIN_PUBLISH_BODY} characters before publishing."
    if problems:
        raise ValidationError("This update is not ready to publish.", details=problems)


# ---------- reading ----------

def _load_options():
    return (
        selectinload(ArtistUpdate.artist),
        selectinload(ArtistUpdate.author),
        selectinload(ArtistUpdate.song).selectinload(Song.credits).selectinload(SongArtist.artist),
        selectinload(ArtistUpdate.album).selectinload(Album.artist),
    )


def get_update(update_id, include_hidden=False, session=None):
    session = session or db.session
    update = session.scalar(
        sa.select(ArtistUpdate).where(ArtistUpdate.id == update_id).options(*_load_options())
    )
    if update is None or (not include_hidden and not update.is_public):
        raise NotFoundError("Update not found.")
    return update


def list_updates(page, per_page, public=True, q=None, status="all", artist=None,
                 artist_id=None, category=None, song_id=None, album_id=None, session=None):
    session = session or db.session
    if status not in STATUSES:
        raise ValidationError(
            "status is invalid.",
            details={"status": "Must be one of: draft, published, archived, all."},
        )
    category = (category or "").strip().lower()
    if category and category not in CATEGORIES:
        raise ValidationError(
            "category is invalid.",
            details={"category": "Must be one of: " + ", ".join(CATEGORIES) + "."},
        )
    q = (q or "").strip()
    if len(q) > MAX_SEARCH_LENGTH:
        raise ValidationError(
            "q is invalid.", details={"q": f"Must be at most {MAX_SEARCH_LENGTH} characters."}
        )
    artist = (artist or "").strip().lower()

    stmt = sa.select(ArtistUpdate)
    if public:
        stmt = stmt.where(
            ArtistUpdate.status == "published",
            ArtistUpdate.artist.has(Artist.archived_at.is_(None)),
        )
        order = [ArtistUpdate.published_at.desc(), ArtistUpdate.id.desc()]
    else:
        if status != "all":
            stmt = stmt.where(ArtistUpdate.status == status)
        order = [ArtistUpdate.updated_at.desc(), ArtistUpdate.id.desc()]

    if category:
        stmt = stmt.where(ArtistUpdate.category == category)
    if artist:
        stmt = stmt.where(ArtistUpdate.artist.has(Artist.slug == artist))
    if artist_id is not None:
        stmt = stmt.where(ArtistUpdate.artist_id == artist_id)
    if song_id is not None:
        stmt = stmt.where(ArtistUpdate.song_id == song_id)
    if album_id is not None:
        stmt = stmt.where(ArtistUpdate.album_id == album_id)
    if q:
        stmt = stmt.where(ArtistUpdate.title.ilike(f"%{escape_like(q)}%", escape="\\"))

    total = session.scalar(sa.select(sa.func.count()).select_from(stmt.subquery()))
    items = session.scalars(
        stmt.options(*_load_options()).order_by(*order).limit(per_page).offset((page - 1) * per_page)
    ).all()
    return items, total


def count_by_status(session=None):
    session = session or db.session
    rows = session.execute(
        sa.select(ArtistUpdate.status, sa.func.count()).group_by(ArtistUpdate.status)
    ).all()
    counts = {"draft": 0, "published": 0, "archived": 0}
    counts.update({status: number for status, number in rows})
    counts["total"] = sum(counts.values())
    return counts


# ---------- writing ----------

def create_update(data, author_id=None, session=None):
    session = session or db.session
    changes = _validate(data, CREATE_FIELDS)
    missing = [f for f in ("artist_id", "title") if changes.get(f) is None]
    if missing:
        raise ValidationError(
            "Missing required fields.", details={f: "This field is required." for f in missing}
        )

    artist = session.get(Artist, changes["artist_id"])
    if artist is None or artist.archived_at is not None:
        raise ValidationError(
            "artist_id is invalid.", details={"artist_id": "No active artist has this id."}
        )
    _check_relations(artist.id, changes.get("song_id"), changes.get("album_id"), session)
    _check_source(changes.get("source_name"), changes.get("source_url"))

    changes.setdefault("body", "")
    update = ArtistUpdate(author_id=author_id, status="draft", **changes)
    session.add(update)
    session.commit()
    return get_update(update.id, include_hidden=True, session=session)


def update_update(update, data, session=None):
    session = session or db.session
    if not isinstance(data, dict) or not data:
        raise ValidationError("Provide at least one field to update.")
    if "artist_id" in data:
        raise ValidationError(
            "artist_id cannot be changed.", details={"artist_id": "Create a new update instead."}
        )
    if update.status == "archived":
        raise ConflictError("This update is archived. Restore it before editing.")

    changes = _validate(data, EDITABLE_FIELDS)
    final = {
        name: changes[name] if name in changes else getattr(update, name)
        for name in EDITABLE_FIELDS
    }
    _check_relations(
        update.artist_id,
        changes.get("song_id"),
        changes.get("album_id"),
        session,
    )
    _check_source(final["source_name"], final["source_url"])
    if update.status == "published":
        _check_publishable(final["title"], final["body"], update.artist)

    for field, value in changes.items():
        setattr(update, field, value)
    session.commit()
    return get_update(update.id, include_hidden=True, session=session)


def publish_update(update, session=None):
    session = session or db.session
    if update.status == "archived":
        raise ConflictError("This update is archived. Restore it first.")
    if update.status != "published":
        _check_publishable(update.title, update.body, update.artist)
        update.status = "published"
        update.published_at = utcnow()
        session.commit()
    return get_update(update.id, include_hidden=True, session=session)


def unpublish_update(update, session=None):
    session = session or db.session
    if update.status == "archived":
        raise ConflictError("This update is archived. Restore it first.")
    if update.status == "published":
        update.status = "draft"
        update.published_at = None
        session.commit()
    return get_update(update.id, include_hidden=True, session=session)


def archive_update(update, session=None):
    session = session or db.session
    if update.status != "archived":
        update.status = "archived"
        session.commit()
    return get_update(update.id, include_hidden=True, session=session)


def restore_update(update, session=None):
    session = session or db.session
    if update.status == "archived":
        update.status = "draft"
        update.published_at = None
        session.commit()
    return get_update(update.id, include_hidden=True, session=session)