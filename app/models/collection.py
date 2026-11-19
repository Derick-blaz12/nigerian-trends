from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.mixins import utcnow


class CollectionRun(db.Model):
    """One execution of a collection job: what it did and how it ended."""

    __tablename__ = "collection_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    data_source_id: Mapped[int] = mapped_column(sa.ForeignKey("data_sources.id"), index=True)
    job: Mapped[str] = mapped_column(sa.String(50))
    status: Mapped[str] = mapped_column(sa.String(20), default="running", server_default="running")
    triggered_by: Mapped[str] = mapped_column(sa.String(20), default="cli", server_default="cli")
    started_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, server_default=sa.func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    requests_made: Mapped[int] = mapped_column(default=0, server_default="0")
    items_seen: Mapped[int] = mapped_column(default=0, server_default="0")
    items_created: Mapped[int] = mapped_column(default=0, server_default="0")
    items_updated: Mapped[int] = mapped_column(default=0, server_default="0")
    items_skipped: Mapped[int] = mapped_column(default=0, server_default="0")
    items_failed: Mapped[int] = mapped_column(default=0, server_default="0")
    error_summary: Mapped[str | None] = mapped_column(sa.Text)

    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'partial', 'failed')",
            name="ck_collection_runs_status",
        ),
        sa.Index("ix_collection_runs_source_job_started", "data_source_id", "job", "started_at"),
    )


class MatchCandidate(db.Model):
    """A possible external identity for one of our artists, waiting for a human decision.

    A 'no_match' row (external_id NULL) remembers that we searched and found nothing,
    so the next run doesn't search for the same artist again straight away.
    """

    __tablename__ = "match_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    artist_id: Mapped[int] = mapped_column(
        sa.ForeignKey("artists.id", ondelete="CASCADE"), index=True
    )
    data_source_id: Mapped[int] = mapped_column(sa.ForeignKey("data_sources.id"))
    external_id: Mapped[str | None] = mapped_column(sa.String(200))
    external_name: Mapped[str | None] = mapped_column(sa.String(200))
    country: Mapped[str | None] = mapped_column(sa.String(2))
    disambiguation: Mapped[str | None] = mapped_column(sa.String(300))
    begin_year: Mapped[int | None]
    score: Mapped[int] = mapped_column(default=0, server_default="0")
    status: Mapped[str] = mapped_column(sa.String(20), default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, server_default=sa.func.now()
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "artist_id", "data_source_id", "external_id",
            name="uq_match_candidates_artist_source_extid",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'rejected', 'no_match')",
            name="ck_match_candidates_status",
        ),
        sa.CheckConstraint(
            "status = 'no_match' OR external_id IS NOT NULL",
            name="ck_match_candidates_has_external_id",
        ),
    )