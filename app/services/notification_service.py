from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.errors import NotFoundError
from app.extensions import db
from app.following.rules import DEFAULT_RULES
from app.models import (
    Album,
    Artist,
    ArtistFollow,
    ArtistUpdate,
    Notification,
    NotificationPreference,
    Song,
    SongArtist,
    User,
)
from app.models.mixins import utcnow
from app.services import song_service
from app.services.feed_service import CREDIT_ROLES, day_start

NOTIFICATION_COLUMNS = ["user_id", "artist_id", "kind", "item_id"]


def _insert_ignoring_duplicates(select_stmt, session):
    """INSERT ... SELECT, skipping anything already notified. Returns how many were new."""
    table = Notification.__table__
    stmt = (
        pg_insert(table)
        .from_select(NOTIFICATION_COLUMNS, select_stmt, include_defaults=False)
        .on_conflict_do_nothing(index_elements=["user_id", "kind", "item_id"])
        .returning(table.c.id)
    )
    return len(session.execute(stmt).all())

def generate_notifications(now=None, session=None, rules=DEFAULT_RULES):
    """Notify followers about recent releases and news. Safe to run as often as you like.

    A follower is notified only if the item is recent, public, and appeared AFTER they
    followed the artist. Importing an old catalogue therefore never notifies anyone.
    """
    session = session or db.session
    now = now or utcnow()
    today = now.date()
    earliest_day = today - timedelta(days=rules.notify_window_days)
    window_start = now - timedelta(days=rules.notify_window_days)

    wants_releases = sa.func.coalesce(NotificationPreference.notify_releases, sa.true()).is_(True)
    wants_news = sa.func.coalesce(NotificationPreference.notify_news, sa.true()).is_(True)

    news = (
        sa.select(
            ArtistFollow.user_id,
            ArtistFollow.artist_id,
            sa.literal_column("'news'"),
            ArtistUpdate.id,
        )
        .select_from(ArtistUpdate)
        .join(Artist, Artist.id == ArtistUpdate.artist_id)
        .join(ArtistFollow, ArtistFollow.artist_id == ArtistUpdate.artist_id)
        .join(User, User.id == ArtistFollow.user_id)
        .outerjoin(NotificationPreference, NotificationPreference.user_id == ArtistFollow.user_id)
        .where(
            ArtistUpdate.status == "published",
            ArtistUpdate.published_at >= window_start,
            ArtistUpdate.published_at <= now,
            Artist.archived_at.is_(None),
            ArtistFollow.notify.is_(True),
            ArtistFollow.created_at <= ArtistUpdate.published_at,
            User.is_active.is_(True),
            wants_news,
        )
    )

    song_appeared = sa.func.greatest(Song.created_at, day_start(Song.release_date))
    songs = (
        sa.select(
            ArtistFollow.user_id,
            sa.func.min(SongArtist.artist_id),
            sa.literal_column("'song'"),
            Song.id,
        )
        .select_from(Song)
        .join(SongArtist, SongArtist.song_id == Song.id)
        .join(ArtistFollow, ArtistFollow.artist_id == SongArtist.artist_id)
        .join(Artist, Artist.id == ArtistFollow.artist_id)
        .join(User, User.id == ArtistFollow.user_id)
        .outerjoin(NotificationPreference, NotificationPreference.user_id == ArtistFollow.user_id)
        .where(
            song_service.public_clause(),
            SongArtist.role.in_(CREDIT_ROLES),
            Song.release_date.is_not(None),
            Song.release_date >= earliest_day,
            Song.release_date <= today,
            Artist.archived_at.is_(None),
            ArtistFollow.notify.is_(True),
            ArtistFollow.created_at <= song_appeared,
            User.is_active.is_(True),
            wants_releases,
        )
        .group_by(ArtistFollow.user_id, Song.id)
    )

    album_appeared = sa.func.greatest(Album.created_at, day_start(Album.release_date))
    albums = (
        sa.select(
            ArtistFollow.user_id,
            ArtistFollow.artist_id,
            sa.literal_column("'album'"),
            Album.id,
        )
        .select_from(Album)
        .join(Artist, Artist.id == Album.artist_id)
        .join(ArtistFollow, ArtistFollow.artist_id == Album.artist_id)
        .join(User, User.id == ArtistFollow.user_id)
        .outerjoin(NotificationPreference, NotificationPreference.user_id == ArtistFollow.user_id)
        .where(
            Album.archived_at.is_(None),
            Album.release_date.is_not(None),
            Album.release_date >= earliest_day,
            Album.release_date <= today,
            Artist.archived_at.is_(None),
            ArtistFollow.notify.is_(True),
            ArtistFollow.created_at <= album_appeared,
            User.is_active.is_(True),
            wants_releases,
        )
    )

    created = {
        "song": _insert_ignoring_duplicates(songs, session),
        "album": _insert_ignoring_duplicates(albums, session),
        "news": _insert_ignoring_duplicates(news, session),
    }
    session.commit()
    return created


def visible_clause():
    """A notification only shows while the item it points at is still public."""
    news_ok = sa.and_(
        Notification.kind == "news",
        Notification.item_id.in_(
            sa.select(ArtistUpdate.id)
            .join(Artist, Artist.id == ArtistUpdate.artist_id)
            .where(ArtistUpdate.status == "published", Artist.archived_at.is_(None))
        ),
    )
    song_ok = sa.and_(
        Notification.kind == "song",
        Notification.item_id.in_(sa.select(Song.id).where(song_service.public_clause())),
    )
    album_ok = sa.and_(
        Notification.kind == "album",
        Notification.item_id.in_(
            sa.select(Album.id)
            .join(Artist, Artist.id == Album.artist_id)
            .where(Album.archived_at.is_(None), Artist.archived_at.is_(None))
        ),
    )
    return sa.or_(news_ok, song_ok, album_ok)


def _conditions(user, unread_only, since):
    conditions = [Notification.user_id == user.id, visible_clause()]
    if unread_only:
        conditions.append(Notification.read_at.is_(None))
    if since is not None:
        conditions.append(Notification.created_at >= since)
    return conditions


def list_notifications(user, page, per_page, unread_only=False, since=None, session=None):
    """Returns ([items], total), newest first. Each item has notification, kind, artist, obj."""
    session = session or db.session
    conditions = _conditions(user, unread_only, since)
    total = session.scalar(sa.select(sa.func.count()).select_from(Notification).where(*conditions))
    rows = session.scalars(
        sa.select(Notification)
        .where(*conditions)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()
    if not rows:
        return [], total

    news_ids = [n.item_id for n in rows if n.kind == "news"]
    album_ids = [n.item_id for n in rows if n.kind == "album"]
    song_ids = [n.item_id for n in rows if n.kind == "song"]
    updates = {}
    if news_ids:
        updates = {
            u.id: u
            for u in session.scalars(sa.select(ArtistUpdate).where(ArtistUpdate.id.in_(news_ids)))
        }
    albums = {}
    if album_ids:
        albums = {
            a.id: a for a in session.scalars(sa.select(Album).where(Album.id.in_(album_ids)))
        }
    songs = song_service.load_public_songs(song_ids, session=session)
    artists = {
        a.id: a
        for a in session.scalars(
            sa.select(Artist).where(Artist.id.in_({n.artist_id for n in rows}))
        )
    }
    sources = {"news": updates, "album": albums, "song": songs}

    items = []
    for notification in rows:
        obj = sources[notification.kind].get(notification.item_id)
        artist = artists.get(notification.artist_id)
        if obj is None or artist is None:
            continue
        items.append(
            {"notification": notification, "kind": notification.kind, "artist": artist, "obj": obj}
        )
    return items, total


def unread_count(user, session=None):
    session = session or db.session
    return session.scalar(
        sa.select(sa.func.count())
        .select_from(Notification)
        .where(*_conditions(user, True, None))
    )


def mark_read(user, notification_id, session=None):
    session = session or db.session
    notification = session.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise NotFoundError("Notification not found.")
    if notification.read_at is None:
        notification.read_at = utcnow()
        session.commit()
    return notification


def mark_all_read(user, session=None):
    """Returns how many notifications were newly marked as read."""
    session = session or db.session
    result = session.execute(
        sa.update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=utcnow())
    )
    session.commit()
    return result.rowcount


def cleanup_notifications(now=None, session=None, rules=DEFAULT_RULES):
    """Delete notifications that were read long ago. Returns how many were removed."""
    session = session or db.session
    cutoff = (now or utcnow()) - timedelta(days=rules.keep_read_days)
    result = session.execute(
        sa.delete(Notification).where(
            Notification.read_at.is_not(None), Notification.read_at < cutoff
        )
    )
    session.commit()
    return result.rowcount