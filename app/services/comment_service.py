from collections import defaultdict
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.orm import aliased

from app.community.guard import ensure_can_post
from app.community.rules import DEFAULT_RULES
from app.community.text import clean_comment_body, normalize_for_compare
from app.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.extensions import db
from app.models import Comment, Song, User
from app.models.mixins import utcnow
from app.services import song_service
from app.services.moderation_service import resolve_open_reports

ALLOWED_CREATE_FIELDS = ("body", "parent_id")


def comment_state(comment):
    """'deleted', or the moderation status: 'visible', 'hidden' or 'removed'."""
    if comment.deleted_at is not None:
        return "deleted"
    return comment.status


def _authors(user_ids, session):
    user_ids = set(user_ids)
    if not user_ids:
        return {}
    return dict(session.execute(sa.select(User.id, User.username).where(User.id.in_(user_ids))).all())


def _reject_unknown(data, allowed):
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object.")
    unknown = [key for key in data if key not in allowed]
    if unknown:
        raise ValidationError("Unknown fields.", details={k: "Unknown field." for k in unknown})


def _check_duplicate(user, song_id, body, session, rules):
    since = utcnow() - timedelta(minutes=rules.duplicate_window_minutes)
    recent = session.scalars(
        sa.select(Comment.body).where(
            Comment.user_id == user.id,
            Comment.song_id == song_id,
            Comment.created_at >= since,
            Comment.deleted_at.is_(None),
        )
    )
    key = normalize_for_compare(body)
    if any(normalize_for_compare(existing) == key for existing in recent):
        raise ConflictError(
            "You already posted this.",
            details={"body": "Duplicate comment."},
            code="duplicate_comment",
        )


def _get_own_comment(user, comment_id, session):
    comment = session.get(Comment, comment_id)
    if comment is None or comment.deleted_at is not None:
        raise NotFoundError("Comment not found.")
    if comment.user_id != user.id:
        raise ForbiddenError("You can only change your own comments.")
    return comment


# ---------- writing ----------

def create_comment(user, song_id, data, session=None, rules=DEFAULT_RULES):
    session = session or db.session
    ensure_can_post(user)
    _reject_unknown(data, ALLOWED_CREATE_FIELDS)
    song_service.get_song(song_id, session=session)  # 404 unless the song is public
    body = clean_comment_body(data.get("body"), rules)

    parent_id = data.get("parent_id")
    if parent_id is not None:
        if isinstance(parent_id, bool) or not isinstance(parent_id, int):
            raise ValidationError(
                "parent_id is invalid.", details={"parent_id": "Must be a whole number."}
            )
        parent = session.get(Comment, parent_id)
        if (
            parent is None
            or parent.song_id != song_id
            or parent.status != "visible"
            or parent.deleted_at is not None
        ):
            raise ValidationError(
                "parent_id is invalid.",
                details={"parent_id": "You can only reply to an existing comment on this song."},
            )
        if parent.parent_id is not None:
            raise ValidationError(
                "parent_id is invalid.",
                details={"parent_id": "Reply to the main comment instead."},
            )

    _check_duplicate(user, song_id, body, session, rules)
    comment = Comment(song_id=song_id, user_id=user.id, parent_id=parent_id, body=body)
    session.add(comment)
    session.commit()
    return comment


def edit_comment(user, comment_id, data, session=None, rules=DEFAULT_RULES):
    session = session or db.session
    ensure_can_post(user)
    _reject_unknown(data, ("body",))
    comment = _get_own_comment(user, comment_id, session)
    if comment.status != "visible":
        raise ConflictError(
            "This comment is under review or was removed, so it can't be edited.",
            code="not_editable",
        )
    if utcnow() - comment.created_at > timedelta(hours=rules.edit_window_hours):
        raise ConflictError("The edit window has closed.", code="edit_window_closed")
    body = clean_comment_body(data.get("body"), rules)
    if body == comment.body:
        return comment
    comment.body = body
    comment.edited_at = utcnow()
    session.commit()
    return comment


def delete_comment(user, comment_id, session=None):
    """The author takes their words back: the text is erased, not just hidden."""
    session = session or db.session
    comment = _get_own_comment(user, comment_id, session)
    comment.body = ""
    comment.deleted_at = utcnow()
    resolve_open_reports(comment.id, "reviewed", None, session)
    session.commit()
    return comment


# ---------- reading ----------

def list_comments(song_id, page, per_page, session=None, rules=DEFAULT_RULES):
    """Top-level comments, newest first, each with its replies (oldest first)."""
    session = session or db.session
    song_service.get_song(song_id, session=session)

    reply = aliased(Comment)
    live = sa.and_(Comment.status == "visible", Comment.deleted_at.is_(None))
    has_live_reply = sa.exists().where(
        reply.parent_id == Comment.id, reply.status == "visible", reply.deleted_at.is_(None)
    )
    # A deleted, hidden or removed comment stays only as a placeholder if replies hang off it.
    base = sa.select(Comment).where(
        Comment.song_id == song_id, Comment.parent_id.is_(None), sa.or_(live, has_live_reply)
    )
    total = session.scalar(sa.select(sa.func.count()).select_from(base.subquery()))
    top = session.scalars(
        base.order_by(Comment.created_at.desc(), Comment.id.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()

    replies = defaultdict(list)
    ids = [comment.id for comment in top]
    if ids:
        rows = session.scalars(
            sa.select(Comment)
            .where(Comment.parent_id.in_(ids), live)
            .order_by(Comment.created_at, Comment.id)
        )
        for item in rows:
            if len(replies[item.parent_id]) < rules.max_thread_replies:
                replies[item.parent_id].append(item)

    user_ids = {comment.user_id for comment in top}
    user_ids |= {item.user_id for group in replies.values() for item in group}
    return {
        "threads": [{"comment": c, "replies": replies.get(c.id, [])} for c in top],
        "authors": _authors(user_ids, session),
        "total": total,
    }


def recent_comments(page, per_page, session=None):
    """The newest visible comments across all public songs, for a discussions feed."""
    session = session or db.session
    base = (
        sa.select(Comment)
        .join(Song, Song.id == Comment.song_id)
        .where(
            Comment.status == "visible",
            Comment.deleted_at.is_(None),
            song_service.public_clause(),
        )
    )
    total = session.scalar(sa.select(sa.func.count()).select_from(base.subquery()))
    comments = session.scalars(
        base.order_by(Comment.created_at.desc(), Comment.id.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()
    songs = song_service.load_public_songs({c.song_id for c in comments}, session=session)
    return {
        "items": [(c, songs[c.song_id]) for c in comments if c.song_id in songs],
        "authors": _authors({c.user_id for c in comments}, session),
        "total": total,
    }