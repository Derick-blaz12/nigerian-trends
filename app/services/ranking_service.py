from datetime import timedelta

import sqlalchemy as sa

from app.community.rules import DEFAULT_RULES
from app.community.scoring import popularity_score
from app.errors import ValidationError
from app.extensions import db
from app.models import Comment, Reaction, User
from app.models.mixins import utcnow
from app.services import song_service

PERIODS = ("trending", "all_time")


def _live_comments():
    return (Comment.status == "visible", Comment.deleted_at.is_(None), User.is_active.is_(True))


def _activity(session, since):
    """Per-song counts from our own community only: likes, recommends, commenters, engaged people."""
    reactions = (
        sa.select(Reaction.song_id, Reaction.kind, sa.func.count())
        .select_from(Reaction)
        .join(User, User.id == Reaction.user_id)
        .where(User.is_active.is_(True))
    )
    if since is not None:
        reactions = reactions.where(Reaction.created_at >= since)
    likes, recommends = {}, {}
    for song_id, kind, number in session.execute(reactions.group_by(Reaction.song_id, Reaction.kind)):
        (likes if kind == "like" else recommends)[song_id] = number

    commenters_query = (
        sa.select(Comment.song_id, sa.func.count(sa.distinct(Comment.user_id)))
        .select_from(Comment)
        .join(User, User.id == Comment.user_id)
        .where(*_live_comments())
    )
    if since is not None:
        commenters_query = commenters_query.where(Comment.created_at >= since)
    commenters = dict(session.execute(commenters_query.group_by(Comment.song_id)).all())

    reaction_pairs = (
        sa.select(Reaction.song_id.label("song_id"), Reaction.user_id.label("user_id"))
        .select_from(Reaction)
        .join(User, User.id == Reaction.user_id)
        .where(User.is_active.is_(True))
    )
    comment_pairs = (
        sa.select(Comment.song_id.label("song_id"), Comment.user_id.label("user_id"))
        .select_from(Comment)
        .join(User, User.id == Comment.user_id)
        .where(*_live_comments())
    )
    if since is not None:
        reaction_pairs = reaction_pairs.where(Reaction.created_at >= since)
        comment_pairs = comment_pairs.where(Comment.created_at >= since)
    pairs = sa.union(reaction_pairs, comment_pairs).subquery()  # one row per person per song
    engaged = dict(
        session.execute(sa.select(pairs.c.song_id, sa.func.count()).group_by(pairs.c.song_id)).all()
    )
    return likes, recommends, commenters, engaged


def song_rankings(period, limit, genre=None, session=None, rules=DEFAULT_RULES):
    """Returns ([ranked items], total ranked). Best first."""
    session = session or db.session
    if period not in PERIODS:
        raise ValidationError(
            "period is invalid.", details={"period": "Must be one of: trending, all_time."}
        )
    since = utcnow() - timedelta(days=rules.trending_days) if period == "trending" else None
    likes, recommends, commenters, engaged = _activity(session, since)

    candidates = [song_id for song_id, people in engaged.items() if people >= rules.min_engaged_users]
    songs = song_service.load_public_songs(candidates, session=session)

    genre = (genre or "").strip().lower()
    items = []
    for song_id, song in songs.items():
        if genre and not any(g.slug == genre for g in song.genres):
            continue
        song_likes = likes.get(song_id, 0)
        song_recs = recommends.get(song_id, 0)
        song_commenters = commenters.get(song_id, 0)
        items.append(
            {
                "song": song,
                "likes": song_likes,
                "recommends": song_recs,
                "commenters": song_commenters,
                "engaged_users": engaged[song_id],
                "score": popularity_score(song_likes, song_recs, song_commenters, rules),
            }
        )
    items.sort(
        key=lambda item: (
            -item["score"],
            -item["engaged_users"],
            -(item["song"].release_date.toordinal() if item["song"].release_date else 0),
            item["song"].id,
        )
    )
    return items[:limit], len(items)