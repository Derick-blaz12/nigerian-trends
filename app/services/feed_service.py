import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import Album, Artist, ArtistFollow, ArtistUpdate, Song, SongArtist
from app.models.mixins import utcnow
from app.services import song_service

CREDIT_ROLES = ("primary", "featured")  # producers and writers don't put a song in your feed


def day_start(column):
    """A release date as a moment (midnight UTC), so it sorts next to real timestamps."""
    return sa.func.timezone(sa.literal_column("'UTC'"), sa.cast(column, sa.DateTime()))


def _followed_artist_ids(user_id):
    return (
        sa.select(ArtistFollow.artist_id)
        .join(Artist, Artist.id == ArtistFollow.artist_id)
        .where(ArtistFollow.user_id == user_id, Artist.archived_at.is_(None))
    )


def feed_items(user, page, per_page, session=None):
    """Returns ([items], total): news, songs and albums from followed artists, newest first.

    One query decides which items and in what order, so pages are always correct.
    Each item is {"kind", "id", "at", "artist", "obj"}.
    """
    session = session or db.session
    today = utcnow().date()
    followed = _followed_artist_ids(user.id)

    news = sa.select(
        sa.literal_column("'news'").label("kind"),
        ArtistUpdate.id.label("item_id"),
        ArtistUpdate.published_at.label("sort_at"),
    ).where(ArtistUpdate.status == "published", ArtistUpdate.artist_id.in_(followed))

    songs = sa.select(
        sa.literal_column("'song'").label("kind"),
        Song.id.label("item_id"),
        day_start(Song.release_date).label("sort_at"),
    ).where(
        song_service.public_clause(),
        Song.release_date.is_not(None),
        Song.release_date <= today,
        Song.id.in_(
            sa.select(SongArtist.song_id).where(
                SongArtist.artist_id.in_(followed), SongArtist.role.in_(CREDIT_ROLES)
            )
        ),
    )

    albums = sa.select(
        sa.literal_column("'album'").label("kind"),
        Album.id.label("item_id"),
        day_start(Album.release_date).label("sort_at"),
    ).where(
        Album.archived_at.is_(None),
        Album.release_date.is_not(None),
        Album.release_date <= today,
        Album.artist_id.in_(followed),
    )

    union = sa.union_all(news, songs, albums).subquery()
    total = session.scalar(sa.select(sa.func.count()).select_from(union))
    rows = session.execute(
        sa.select(union.c.kind, union.c.item_id, union.c.sort_at)
        .order_by(union.c.sort_at.desc(), union.c.kind, union.c.item_id.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()

    ids = {"news": [], "song": [], "album": []}
    for kind, item_id, _ in rows:
        ids[kind].append(item_id)

    updates = {}
    if ids["news"]:
        updates = {
            u.id: u
            for u in session.scalars(
                sa.select(ArtistUpdate)
                .where(ArtistUpdate.id.in_(ids["news"]))
                .options(selectinload(ArtistUpdate.artist))
            )
        }
    songs_by_id = song_service.load_public_songs(ids["song"], session=session)
    albums_by_id = {}
    if ids["album"]:
        albums_by_id = {
            a.id: a
            for a in session.scalars(
                sa.select(Album).where(Album.id.in_(ids["album"])).options(selectinload(Album.artist))
            )
        }
    followed_ids = set(session.scalars(followed))

    items = []
    for kind, item_id, at in rows:
        if kind == "news":
            obj = updates.get(item_id)
            artist = obj.artist if obj is not None else None
        elif kind == "song":
            obj = songs_by_id.get(item_id)
            artist = None
            if obj is not None:
                artist = next(
                    (
                        credit.artist
                        for credit in obj.credits
                        if credit.artist_id in followed_ids and credit.role in CREDIT_ROLES
                    ),
                    None,
                )
        else:
            obj = albums_by_id.get(item_id)
            artist = obj.artist if obj is not None else None
        if obj is None or artist is None:
            continue
        items.append({"kind": kind, "id": item_id, "at": at, "artist": artist, "obj": obj})
    return items, total