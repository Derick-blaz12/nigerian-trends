from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.mixins import TimestampMixin, utcnow


class Comment(TimestampMixin, db.Model):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    song_id: Mapped[int] = mapped_column(sa.ForeignKey("songs.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("comments.id", ondelete="CASCADE")
    )
    body: Mapped[str] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.String(20), default="visible", server_default="visible")
    edited_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    __table_args__ = (
        sa.Index("ix_comments_song_created", "song_id", "created_at"),
        sa.CheckConstraint(
            "status IN ('visible', 'hidden', 'removed')", name="ck_comments_status"
        ),
    )


class Reaction(db.Model):
    __tablename__ = "reactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    song_id: Mapped[int] = mapped_column(
        sa.ForeignKey("songs.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(sa.String(20))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, server_default=sa.func.now()
    )

    __table_args__ = (
        sa.UniqueConstraint("user_id", "song_id", "kind", name="uq_reactions_user_song_kind"),
        sa.CheckConstraint("kind IN ('like', 'recommend')", name="ck_reactions_kind"),
    )


class CommentReport(db.Model):
    __tablename__ = "comment_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    comment_id: Mapped[int] = mapped_column(
        sa.ForeignKey("comments.id", ondelete="CASCADE"), index=True
    )
    reporter_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(sa.String(500))
    status: Mapped[str] = mapped_column(sa.String(20), default="open", server_default="open")
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, server_default=sa.func.now()
    )

    __table_args__ = (
        sa.UniqueConstraint("comment_id", "reporter_id", name="uq_comment_reports_comment_reporter"),
        sa.CheckConstraint(
            "status IN ('open', 'reviewed', 'dismissed')", name="ck_comment_reports_status"
        ),
    )


class ArtistFollow(db.Model):
    __tablename__ = "artist_follows"

    user_id: Mapped[int] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    artist_id: Mapped[int] = mapped_column(
        sa.ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, server_default=sa.func.now()
    )