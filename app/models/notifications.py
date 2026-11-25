from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.mixins import utcnow


class NotificationPreference(db.Model):
    """Per-user notification settings. A missing row means the defaults."""

    __tablename__ = "notification_preferences"

    user_id: Mapped[int] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    notify_releases: Mapped[bool] = mapped_column(default=True, server_default=sa.true())
    notify_news: Mapped[bool] = mapped_column(default=True, server_default=sa.true())
    email_digest: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, onupdate=utcnow,
        server_default=sa.func.now(),
    )


class Notification(db.Model):
    """'A new song, album or story from an artist you follow.' It points at the item
    instead of copying its text, so unpublishing the item makes the notification vanish."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    artist_id: Mapped[int] = mapped_column(sa.ForeignKey("artists.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(sa.String(20))
    item_id: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, server_default=sa.func.now()
    )
    read_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    __table_args__ = (
        sa.UniqueConstraint("user_id", "kind", "item_id", name="uq_notifications_user_kind_item"),
        sa.CheckConstraint("kind IN ('song', 'album', 'news')", name="ck_notifications_kind"),
        sa.Index("ix_notifications_user_created", "user_id", "created_at"),
    )