import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.errors import ConflictError, NotFoundError, ValidationError
from app.extensions import db
from app.following.rules import DEFAULT_RULES
from app.models import Artist, ArtistFollow, User


def _find_artist(slug, session, include_archived=False):
    stmt = sa.select(Artist).where(Artist.slug == slug)
    if not include_archived:
        stmt = stmt.where(Artist.archived_at.is_(None))
    artist = session.scalar(stmt)
    if artist is None:
        raise NotFoundError("Artist not found.")
    return artist


def _check_notify(notify):
    if notify is not None and not isinstance(notify, bool):
        raise ValidationError("notify is invalid.", details={"notify": "Must be true or false."})


def follow_artist(user, slug, notify=None, session=None, rules=DEFAULT_RULES):
    """Follow an artist. Returns (follow, changed). Repeating the call changes nothing."""
    session = session or db.session
    _check_notify(notify)
    artist = _find_artist(slug, session)
    key = (user.id, artist.id)

    existing = session.get(ArtistFollow, key)
    if existing is not None:
        if notify is not None and existing.notify != notify:
            existing.notify = notify
            session.commit()
            return existing, True
        return existing, False

    total = session.scalar(
        sa.select(sa.func.count())
        .select_from(ArtistFollow)
        .join(Artist, Artist.id == ArtistFollow.artist_id)
        .where(ArtistFollow.user_id == user.id, Artist.archived_at.is_(None))
    )
    if total >= rules.max_follows:
        raise ConflictError(
            f"You can follow up to {rules.max_follows} artists.", code="follow_limit"
        )

    follow = ArtistFollow(
        user_id=user.id, artist_id=artist.id, notify=True if notify is None else notify
    )
    session.add(follow)
    try:
        session.commit()
    except IntegrityError:  # a double tap beat us to it
        session.rollback()
        return session.get(ArtistFollow, key), False
    return follow, True


def unfollow_artist(user, slug, session=None):
    """Returns True if a follow was removed. Works for archived artists, so nobody gets stuck."""
    session = session or db.session
    artist = _find_artist(slug, session, include_archived=True)
    result = session.execute(
        sa.delete(ArtistFollow).where(
            ArtistFollow.user_id == user.id, ArtistFollow.artist_id == artist.id
        )
    )
    session.commit()
    return result.rowcount > 0


def follow_status(slug, viewer_id=None, session=None):
    """The public follower count, plus what the signed-in viewer has chosen."""
    session = session or db.session
    artist = _find_artist(slug, session)
    followers = session.scalar(
        sa.select(sa.func.count())
        .select_from(ArtistFollow)
        .join(User, User.id == ArtistFollow.user_id)
        .where(ArtistFollow.artist_id == artist.id, User.is_active.is_(True))
    )
    data = {"followers": followers}
    if viewer_id is not None:
        mine = session.get(ArtistFollow, (viewer_id, artist.id))
        data["me"] = {
            "following": mine is not None,
            "notify": bool(mine.notify) if mine is not None else False,
        }
    return data


def list_following(user, page, per_page, session=None):
    """The artists a person follows, newest follow first. Archived artists are hidden."""
    session = session or db.session
    visible = (ArtistFollow.user_id == user.id, Artist.archived_at.is_(None))
    total = session.scalar(
        sa.select(sa.func.count())
        .select_from(ArtistFollow)
        .join(Artist, Artist.id == ArtistFollow.artist_id)
        .where(*visible)
    )
    rows = session.execute(
        sa.select(ArtistFollow, Artist)
        .join(Artist, Artist.id == ArtistFollow.artist_id)
        .where(*visible)
        .options(selectinload(Artist.genres))
        .order_by(ArtistFollow.created_at.desc(), Artist.id)
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()
    return rows, total