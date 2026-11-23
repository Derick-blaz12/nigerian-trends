import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.community.guard import ensure_can_post
from app.errors import ValidationError
from app.extensions import db
from app.models import Comment, Reaction, User
from app.services import song_service

KINDS = ("like", "recommend")


def _check_kind(kind):
    if kind not in KINDS:
        raise ValidationError("kind is invalid.", details={"kind": "Must be one of: like, recommend."})


def set_reaction(user, song_id, kind, session=None):
    """Returns True if the reaction was added, False if it was already there."""
    session = session or db.session
    _check_kind(kind)
    ensure_can_post(user)
    song_service.get_song(song_id, session=session)  # 404 unless the song is public
    existing = session.scalar(
        sa.select(Reaction.id).where(
            Reaction.user_id == user.id, Reaction.song_id == song_id, Reaction.kind == kind
        )
    )
    if existing is not None:
        return False
    session.add(Reaction(user_id=user.id, song_id=song_id, kind=kind))
    try:
        session.commit()
    except IntegrityError:  # a double tap beat us to it
        session.rollback()
        return False
    return True


def remove_reaction(user, song_id, kind, session=None):
    """Returns True if a reaction was removed. Muted users can still take theirs back."""
    session = session or db.session
    _check_kind(kind)
    result = session.execute(
        sa.delete(Reaction).where(
            Reaction.user_id == user.id, Reaction.song_id == song_id, Reaction.kind == kind
        )
    )
    session.commit()
    return result.rowcount > 0


def song_stats(song_id, viewer_id=None, session=None):
    """Community numbers for one song, plus what the viewer has done, if signed in."""
    session = session or db.session
    song_service.get_song(song_id, session=session)
    active = User.is_active.is_(True)

    counts = dict(
        session.execute(
            sa.select(Reaction.kind, sa.func.count())
            .select_from(Reaction)
            .join(User, User.id == Reaction.user_id)
            .where(Reaction.song_id == song_id, active)
            .group_by(Reaction.kind)
        ).all()
    )
    comments, commenters = session.execute(
        sa.select(sa.func.count(), sa.func.count(sa.distinct(Comment.user_id)))
        .select_from(Comment)
        .join(User, User.id == Comment.user_id)
        .where(
            Comment.song_id == song_id,
            Comment.status == "visible",
            Comment.deleted_at.is_(None),
            active,
        )
    ).one()

    data = {
        "likes": counts.get("like", 0),
        "recommends": counts.get("recommend", 0),
        "comments": comments,
        "commenters": commenters,
    }
    if viewer_id is not None:
        mine = set(
            session.scalars(
                sa.select(Reaction.kind).where(
                    Reaction.song_id == song_id, Reaction.user_id == viewer_id
                )
            )
        )
        data["me"] = {"liked": "like" in mine, "recommended": "recommend" in mine}
    return data