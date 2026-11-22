import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.errors import ConflictError, NotFoundError, ValidationError
from app.extensions import db
from app.models import Album, Artist, Genre, Song, SongArtist
from app.models.mixins import utcnow
from app.services.genre_service import load_genres
from app.utils.catalogue import escape_like, normalize_isrc, parse_release_date, title_key
from app.utils.validation import clean_string

EDITABLE_FIELDS = (
    "title", "release_date", "duration_seconds", "track_number",
    "isrc", "album_id", "genres", "artists",
)
ROLES = ("primary", "featured", "producer", "writer")
STATUSES = ("active", "archived", "all")
MAX_CREDITS = 15
MAX_SEARCH_LENGTH = 100


# ---------- validation ----------

def _whole_number(value, field, minimum, maximum):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValidationError(
            f"{field} is invalid.",
            details={field: f"Must be a whole number between {minimum} and {maximum}."},
        )
    return value


def _parse_credits(raw, session):
    def invalid(message):
        return ValidationError("artists is invalid.", details={"artists": message})

    if not isinstance(raw, list) or not raw or len(raw) > MAX_CREDITS:
        raise invalid(f"Provide between 1 and {MAX_CREDITS} credits.")

    credits, seen = [], set()
    for item in raw:
        if not isinstance(item, dict) or set(item) - {"artist_id", "role"}:
            raise invalid("Each credit must be an object with artist_id and role.")
        artist_id = item.get("artist_id")
        role = item.get("role", "primary")
        if isinstance(artist_id, bool) or not isinstance(artist_id, int):
            raise invalid("artist_id must be a whole number.")
        if role not in ROLES:
            raise invalid("role must be one of: " + ", ".join(ROLES) + ".")
        if (artist_id, role) in seen:
            raise invalid("The same artist cannot have the same role twice.")
        seen.add((artist_id, role))
        credits.append({"artist_id": artist_id, "role": role})

    if not any(c["role"] == "primary" for c in credits):
        raise invalid("At least one primary artist is required.")

    ids = {c["artist_id"] for c in credits}
    found = {a.id: a for a in session.scalars(sa.select(Artist).where(Artist.id.in_(ids)))}
    missing = sorted(ids - found.keys())
    if missing:
        raise invalid("Unknown artist ids: " + ", ".join(str(i) for i in missing) + ".")
    archived = sorted(found[i].name for i in ids if found[i].archived_at is not None)
    if archived:
        raise invalid("Archived artists cannot be credited: " + ", ".join(archived) + ".")
    return credits


def _validate(data, session):
    """Validate every field first, so a bad request changes nothing."""
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object.")
    unknown = [key for key in data if key not in EDITABLE_FIELDS]
    if unknown:
        raise ValidationError("Unknown fields.", details={k: "Unknown field." for k in unknown})

    changes = {}
    if "title" in data:
        changes["title"] = clean_string(data["title"], "title", min_len=1, max_len=200)
    if "release_date" in data:
        changes["release_date"] = parse_release_date(data["release_date"])
    if "duration_seconds" in data:
        changes["duration_seconds"] = _whole_number(data["duration_seconds"], "duration_seconds", 1, 7200)
    if "track_number" in data:
        changes["track_number"] = _whole_number(data["track_number"], "track_number", 1, 200)
    if "isrc" in data:
        changes["isrc"] = normalize_isrc(data["isrc"])
    if "album_id" in data:
        changes["album_id"] = _whole_number(data["album_id"], "album_id", 1, 2_147_483_647)
    if "genres" in data:
        changes["genres"] = load_genres(data["genres"], session)
    if "artists" in data:
        changes["credits"] = _parse_credits(data["artists"], session)
    return changes


def _check_duplicates(title, credits, isrc, session, song_id=None):
    if isrc:
        stmt = sa.select(Song.id).where(Song.isrc == isrc)
        if song_id is not None:
            stmt = stmt.where(Song.id != song_id)
        existing = session.scalar(stmt)
        if existing is not None:
            raise ConflictError(
                "A song with this ISRC already exists.",
                details={"isrc": f"Already used by song {existing}."},
            )

    primary_ids = [c["artist_id"] for c in credits if c["role"] == "primary"]
    stmt = sa.select(Song).where(
        Song.id.in_(
            sa.select(SongArtist.song_id).where(
                SongArtist.role == "primary", SongArtist.artist_id.in_(primary_ids)
            )
        )
    )
    if song_id is not None:
        stmt = stmt.where(Song.id != song_id)
    key = title_key(title)
    for other in session.scalars(stmt):
        if title_key(other.title) == key:
            note = " (archived)" if other.archived_at else ""
            raise ConflictError(
                "This song looks like a duplicate.",
                details={
                    "title": (
                        f"'{other.title}'{note} by the same primary artist already exists "
                        f"(song {other.id}). For a remix or live version, put it in the title, "
                        "e.g. 'Song (Remix)'."
                    )
                },
            )


def _check_album(album_id, credits, track_number, session, song_id=None):
    if album_id is None:
        if track_number is not None:
            raise ValidationError(
                "track_number needs an album.", details={"track_number": "Set an album first."}
            )
        return
    album = session.get(Album, album_id)
    if album is None:
        raise ValidationError("album_id is invalid.", details={"album_id": "No album has this id."})
    if album.archived_at is not None:
        raise ValidationError("album_id is invalid.", details={"album_id": "This album is archived."})
    if album.artist_id not in {c["artist_id"] for c in credits}:
        raise ValidationError(
            "album_id is invalid.",
            details={"album_id": "The album's artist must be credited on the song."},
        )
    if track_number is not None:
        stmt = sa.select(Song.id).where(
            Song.album_id == album_id,
            Song.track_number == track_number,
            Song.archived_at.is_(None),
        )
        if song_id is not None:
            stmt = stmt.where(Song.id != song_id)
        clash = session.scalar(stmt)
        if clash is not None:
            raise ConflictError(
                "That track number is taken.",
                details={"track_number": f"Track {track_number} on this album is song {clash}."},
            )


def _apply_credits(song, credits):
    """Make the song's credits match `credits`, changing only what differs."""
    existing = {(c.artist_id, c.role): c for c in song.credits}
    wanted = {(c["artist_id"], c["role"]): index for index, c in enumerate(credits)}
    for key, credit in list(existing.items()):
        if key not in wanted:
            song.credits.remove(credit)  # delete-orphan removes the row
    for (artist_id, role), position in wanted.items():
        if (artist_id, role) in existing:
            existing[(artist_id, role)].position = position
        else:
            song.credits.append(SongArtist(artist_id=artist_id, role=role, position=position))


# ---------- reading ----------

def _load_options():
    return (
        selectinload(Song.credits).selectinload(SongArtist.artist),
        selectinload(Song.genres),
        selectinload(Song.album),
    )


def _public_clause():
    return sa.and_(
        Song.archived_at.is_(None),
        Song.credits.any(
            sa.and_(
                SongArtist.role == "primary",
                SongArtist.artist.has(Artist.archived_at.is_(None)),
            )
        ),
    )


def get_song(song_id, include_hidden=False, session=None):
    session = session or db.session
    song = session.scalar(sa.select(Song).where(Song.id == song_id).options(*_load_options()))
    if song is None or (not include_hidden and not song.is_public):
        raise NotFoundError("Song not found.")
    return song


def list_songs(page, per_page, q=None, genre=None, artist=None,
               status="active", public=True, session=None):
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
    artist = (artist or "").strip().lower()

    stmt = sa.select(Song)
    if public:
        stmt = stmt.where(_public_clause())
    elif status == "active":
        stmt = stmt.where(Song.archived_at.is_(None))
    elif status == "archived":
        stmt = stmt.where(Song.archived_at.is_not(None))
    if genre:
        stmt = stmt.where(Song.genres.any(Genre.slug == genre))
    if artist:
        condition = Artist.slug == artist
        if public:
            condition = sa.and_(condition, Artist.archived_at.is_(None))
        stmt = stmt.where(Song.credits.any(SongArtist.artist.has(condition)))

    order = [Song.release_date.desc().nulls_last(), Song.id.desc()]
    if q:
        escaped = escape_like(q)
        title_match = Song.title.ilike(f"%{escaped}%", escape="\\")
        artist_match = Song.credits.any(
            SongArtist.artist.has(Artist.name.ilike(f"%{escaped}%", escape="\\"))
        )
        stmt = stmt.where(sa.or_(title_match, artist_match))
        rank = sa.case(
            (Song.title.ilike(f"{escaped}%", escape="\\"), 0), (title_match, 1), else_=2
        )
        order = [rank, *order]

    total = session.scalar(sa.select(sa.func.count()).select_from(stmt.subquery()))
    items = session.scalars(
        stmt.options(*_load_options()).order_by(*order).limit(per_page).offset((page - 1) * per_page)
    ).all()
    return items, total


# ---------- writing ----------

def create_song(data, session=None):
    session = session or db.session
    changes = _validate(data, session)
    missing = [f for f in ("title", "credits") if f not in changes]
    if missing:
        raise ValidationError(
            "Missing required fields.",
            details={("artists" if f == "credits" else f): "This field is required." for f in missing},
        )

    _check_duplicates(changes["title"], changes["credits"], changes.get("isrc"), session)
    _check_album(changes.get("album_id"), changes["credits"], changes.get("track_number"), session)

    credits = changes.pop("credits")
    genres = changes.pop("genres", [])
    song = Song(**changes)
    song.genres = genres
    _apply_credits(song, credits)
    session.add(song)
    try:
        session.commit()
    except IntegrityError:  # e.g. two admins using the same ISRC at the same instant
        session.rollback()
        raise ConflictError("A song with these details already exists.") from None
    return get_song(song.id, include_hidden=True, session=session)


def update_song(song, data, session=None):
    session = session or db.session
    if not isinstance(data, dict) or not data:
        raise ValidationError("Provide at least one field to update.")
    changes = _validate(data, session)
    # Taking a song off its album also clears its track number.
    if "album_id" in changes and changes["album_id"] is None and "track_number" not in changes:
        changes["track_number"] = None

    final_credits = changes.get("credits") or [
        {"artist_id": c.artist_id, "role": c.role} for c in song.credits
    ]
    final_title = changes.get("title", song.title)
    final_isrc = changes["isrc"] if "isrc" in changes else song.isrc
    final_album = changes["album_id"] if "album_id" in changes else song.album_id
    final_track = changes["track_number"] if "track_number" in changes else song.track_number

    if {"title", "credits", "isrc"} & changes.keys():
        _check_duplicates(final_title, final_credits, final_isrc, session, song_id=song.id)
    if {"album_id", "track_number", "credits"} & changes.keys():
        _check_album(final_album, final_credits, final_track, session, song_id=song.id)

    credits = changes.pop("credits", None)
    genres = changes.pop("genres", None)
    for field, value in changes.items():
        setattr(song, field, value)
    if genres is not None:
        song.genres = genres
    if credits is not None:
        _apply_credits(song, credits)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ConflictError("A song with these details already exists.") from None
    return get_song(song.id, include_hidden=True, session=session)


def archive_song(song, session=None):
    session = session or db.session
    if song.archived_at is None:
        song.archived_at = utcnow()
        session.commit()
    return get_song(song.id, include_hidden=True, session=session)


def restore_song(song, session=None):
    session = session or db.session
    if song.archived_at is not None:
        song.archived_at = None
        session.commit()
    return get_song(song.id, include_hidden=True, session=session)

def public_clause():
    """SQL condition for songs the public can see."""
    return _public_clause()


def load_public_songs(song_ids, session=None):
    """Public songs by id (credits, genres and album loaded), as {id: song}."""
    session = session or db.session
    song_ids = list(song_ids)
    if not song_ids:
        return {}
    songs = session.scalars(
        sa.select(Song).where(Song.id.in_(song_ids), _public_clause()).options(*_load_options())
    ).all()
    return {song.id: song for song in songs}