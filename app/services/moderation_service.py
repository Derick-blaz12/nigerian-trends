from collections import defaultdict
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.community.guard import ensure_can_post
from app.community.rules import DEFAULT_RULES
from app.errors import ConflictError, NotFoundError, ValidationError
from app.extensions import db
from app.models import Comment, CommentReport, Song, User
from app.models.mixins import utcnow
from app.utils.validation import clean_string

REPORT_REASONS = ("spam", "abuse", "hate", "sexual", "misinformation", "other")
MAX_DETAILS = 400
MAX_NOTE = 300


def resolve_open_reports(comment_id, status, resolver_id, session):
    """Close every open report on a comment (status: 'reviewed' or 'dismissed')."""
    session.execute(
        sa.update(CommentReport)
        .where(CommentReport.comment_id == comment_id, CommentReport.status == "open")
        .values(status=status, resolved_by=resolver_id, resolved_at=utcnow())
    )


def _clean_note(note):
    if note in (None, ""):
        return None
    return clean_string(note, "note", min_len=1, max_len=MAX_NOTE)


def _get_comment(comment_id, session):
    comment = session.get(Comment, comment_id)
    if comment is None:
        raise NotFoundError("Comment not found.")
    return comment


# ---------- reporting ----------

def report_comment(user, comment_id, reason, details=None, session=None, rules=DEFAULT_RULES):
    session = session or db.session
    ensure_can_post(user)
    if reason not in REPORT_REASONS:
        raise ValidationError(
            "reason is invalid.",
            details={"reason": "Must be one of: " + ", ".join(REPORT_REASONS) + "."},
        )
    details = (
        None if details in (None, "") else clean_string(details, "details", 1, MAX_DETAILS)
    )
    comment = session.get(Comment, comment_id)
    if comment is None or comment.deleted_at is not None or comment.status != "visible":
        raise NotFoundError("Comment not found.")
    if comment.user_id == user.id:
        raise ValidationError(
            "You can't report your own comment.", details={"comment": "This is your own comment."}
        )

    report = CommentReport(
        comment_id=comment.id,
        reporter_id=user.id,
        reason=reason if details is None else f"{reason}: {details}",
    )
    session.add(report)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ConflictError("You already reported this comment.", code="already_reported") from None

    open_reports = session.scalar(
        sa.select(sa.func.count())
        .select_from(CommentReport)
        .where(CommentReport.comment_id == comment_id, CommentReport.status == "open")
    )
    if open_reports >= rules.auto_hide_reports:
        comment = session.get(Comment, comment_id)
        if comment.status == "visible":
            comment.status = "hidden"
            comment.moderated_at = utcnow()
            comment.moderation_note = "Hidden automatically after reports."
            session.commit()
    return report


def report_queue(page, per_page, session=None):
    """Comments with open reports, most reported first."""
    session = session or db.session
    counts = (
        sa.select(
            CommentReport.comment_id.label("comment_id"),
            sa.func.count().label("n"),
            sa.func.max(CommentReport.created_at).label("last"),
        )
        .where(CommentReport.status == "open")
        .group_by(CommentReport.comment_id)
        .subquery()
    )
    total = session.scalar(sa.select(sa.func.count()).select_from(counts))
    rows = session.execute(
        sa.select(Comment, User, Song.title, counts.c.n)
        .select_from(Comment)
        .join(counts, counts.c.comment_id == Comment.id)
        .join(User, User.id == Comment.user_id)
        .join(Song, Song.id == Comment.song_id)
        .order_by(counts.c.n.desc(), counts.c.last.desc(), Comment.id)
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()

    ids = [comment.id for comment, _, _, _ in rows]
    reports = defaultdict(list)
    if ids:
        report_rows = session.execute(
            sa.select(CommentReport, User.username)
            .join(User, User.id == CommentReport.reporter_id)
            .where(CommentReport.comment_id.in_(ids), CommentReport.status == "open")
            .order_by(CommentReport.created_at, CommentReport.id)
        )
        for report, username in report_rows:
            reports[report.comment_id].append((report, username))
    items = [
        {
            "comment": comment,
            "author": author,
            "song_title": title,
            "report_count": count,
            "reports": reports[comment.id],
        }
        for comment, author, title, count in rows
    ]
    return items, total


# ---------- admin actions ----------

def remove_comment(admin, comment_id, note=None, session=None):
    session = session or db.session
    note = _clean_note(note)
    comment = _get_comment(comment_id, session)
    if comment.deleted_at is not None:
        raise ConflictError("The author already deleted this comment.")
    if comment.status == "removed":
        raise ConflictError("This comment is already removed.")
    comment.status = "removed"
    comment.moderated_by = admin.id
    comment.moderated_at = utcnow()
    comment.moderation_note = note
    resolve_open_reports(comment.id, "reviewed", admin.id, session)
    session.commit()
    return comment


def dismiss_reports(admin, comment_id, session=None):
    """The reports were wrong: close them, and show the comment again if it was auto-hidden."""
    session = session or db.session
    comment = _get_comment(comment_id, session)
    if comment.deleted_at is not None:
        raise ConflictError("The author already deleted this comment.")
    if comment.status == "removed":
        raise ConflictError("This comment was removed. Restore it instead.")
    if comment.status == "hidden":
        comment.status = "visible"
        comment.moderated_by = admin.id
        comment.moderated_at = utcnow()
        comment.moderation_note = None
    resolve_open_reports(comment.id, "dismissed", admin.id, session)
    session.commit()
    return comment


def restore_comment(admin, comment_id, session=None):
    session = session or db.session
    comment = _get_comment(comment_id, session)
    if comment.deleted_at is not None:
        raise ConflictError("The author already deleted this comment.")
    if comment.status != "removed":
        raise ConflictError("Only removed comments can be restored.")
    comment.status = "visible"
    comment.moderated_by = admin.id
    comment.moderated_at = utcnow()
    comment.moderation_note = None
    session.commit()
    return comment


def mute_user(admin, user_id, days, session=None, rules=DEFAULT_RULES):
    session = session or db.session
    if (
        isinstance(days, bool)
        or not isinstance(days, int)
        or not 1 <= days <= rules.max_mute_days
    ):
        raise ValidationError(
            "days is invalid.",
            details={"days": f"Must be a whole number from 1 to {rules.max_mute_days}."},
        )
    user = session.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found.")
    if user.is_admin:
        raise ConflictError("Administrators can't be muted.")
    user.muted_until = utcnow() + timedelta(days=days)
    session.commit()
    return user


def unmute_user(user_id, session=None):
    session = session or db.session
    user = session.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found.")
    user.muted_until = None
    session.commit()
    return user