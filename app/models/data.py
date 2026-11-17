from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.mixins import TimestampMixin, utcnow


class DataSource(TimestampMixin, db.Model):
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(80), unique=True)
    base_url: Mapped[str | None] = mapped_column(sa.String(300))
    terms_url: Mapped[str | None] = mapped_column(sa.String(300))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=sa.true())
    notes: Mapped[str | None] = mapped_column(sa.Text)


class ArtistExternalId(db.Model):
    __tablename__ = "artist_external_ids"

    id: Mapped[int] = mapped_column(primary_key=True)
    artist_id: Mapped[int] = mapped_column(sa.ForeignKey("artists.id", ondelete="CASCADE"))
    data_source_id: Mapped[int] = mapped_column(sa.ForeignKey("data_sources.id"))
    external_id: Mapped[str] = mapped_column(sa.String(200))

    __table_args__ = (
        sa.UniqueConstraint("data_source_id", "external_id", name="uq_artist_ext_source_extid"),
        sa.UniqueConstraint("artist_id", "data_source_id", name="uq_artist_ext_artist_source"),
    )


class MetricSnapshot(db.Model):
    __tablename__ = "metric_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    artist_id: Mapped[int] = mapped_column(sa.ForeignKey("artists.id", ondelete="CASCADE"))
    data_source_id: Mapped[int] = mapped_column(sa.ForeignKey("data_sources.id"))
    metric_type: Mapped[str] = mapped_column(sa.String(50))
    value: Mapped[int] = mapped_column(sa.BigInteger)
    captured_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, server_default=sa.func.now()
    )

    __table_args__ = (
        sa.Index("ix_metric_artist_type_time", "artist_id", "metric_type", "captured_at"),
        sa.UniqueConstraint(
            "artist_id", "data_source_id", "metric_type", "captured_at",
            name="uq_metric_snapshot",
        ),
    )