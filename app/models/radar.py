from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.mixins import TimestampMixin


class RadarEntry(TimestampMixin, db.Model):
    """An editor's decision about one artist: a pick (shown) or an exclusion (hidden)."""

    __tablename__ = "radar_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    artist_id: Mapped[int] = mapped_column(
        sa.ForeignKey("artists.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[str] = mapped_column(sa.String(20))
    note: Mapped[str | None] = mapped_column(sa.String(200))
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (
        sa.CheckConstraint("status IN ('pick', 'excluded')", name="ck_radar_entries_status"),
    )