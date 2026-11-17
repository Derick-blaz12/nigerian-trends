from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.mixins import TimestampMixin


class ArtistUpdate(TimestampMixin, db.Model):
    __tablename__ = "artist_updates"

    id: Mapped[int] = mapped_column(primary_key=True)
    artist_id: Mapped[int] = mapped_column(
        sa.ForeignKey("artists.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    song_id: Mapped[int | None] = mapped_column(sa.ForeignKey("songs.id", ondelete="SET NULL"))
    album_id: Mapped[int | None] = mapped_column(sa.ForeignKey("albums.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(sa.String(200))
    body: Mapped[str] = mapped_column(sa.Text)
    category: Mapped[str] = mapped_column(sa.String(30), default="news", server_default="news")
    source_name: Mapped[str | None] = mapped_column(sa.String(150))
    source_url: Mapped[str | None] = mapped_column(sa.String(500))
    status: Mapped[str] = mapped_column(sa.String(20), default="draft", server_default="draft")
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), index=True)

    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')", name="ck_artist_updates_status"
        ),
        sa.CheckConstraint(
            "category IN ('news', 'release', 'interview', 'event')",
            name="ck_artist_updates_category",
        ),
        sa.CheckConstraint(
            "status <> 'published' OR published_at IS NOT NULL",
            name="ck_artist_updates_published_has_date",
        ),
    )