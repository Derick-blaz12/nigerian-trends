import re
from datetime import timedelta, timezone

import sqlalchemy as sa

from app.errors import ValidationError
from app.extensions import db
from app.models import MetricSnapshot
from app.models.mixins import utcnow

METRIC_RE = re.compile(r"[a-z][a-z0-9_]{1,49}")


def record_snapshot(artist_id, data_source_id, metric_type, value, captured_at=None, session=None):
    """Store one measurement. At most one per artist, source and metric per UTC day.

    Returns the new snapshot, or None if today's was already recorded.
    """
    session = session or db.session
    if not isinstance(metric_type, str) or not METRIC_RE.fullmatch(metric_type):
        raise ValidationError(
            "metric_type is invalid.",
            details={"metric_type": "Use lowercase letters, numbers and underscores."},
        )
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError(
            "value is invalid.", details={"value": "Must be a whole number, zero or more."}
        )
    captured_at = captured_at or utcnow()
    if captured_at.tzinfo is None:
        raise ValidationError(
            "captured_at is invalid.", details={"captured_at": "Must include a timezone."}
        )

    day_start = captured_at.astimezone(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    existing = session.scalar(
        sa.select(MetricSnapshot.id).where(
            MetricSnapshot.artist_id == artist_id,
            MetricSnapshot.data_source_id == data_source_id,
            MetricSnapshot.metric_type == metric_type,
            MetricSnapshot.captured_at >= day_start,
            MetricSnapshot.captured_at < day_start + timedelta(days=1),
        )
    )
    if existing is not None:
        return None

    snapshot = MetricSnapshot(
        artist_id=artist_id,
        data_source_id=data_source_id,
        metric_type=metric_type,
        value=value,
        captured_at=captured_at,
    )
    session.add(snapshot)
    session.commit()
    return snapshot