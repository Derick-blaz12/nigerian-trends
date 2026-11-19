from datetime import datetime, timedelta, timezone

import pytest

from app.collectors import sync
from app.errors import ValidationError
from app.services import artist_service, metric_service

NOON = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


def ids():
    return artist_service.create_artist({"name": "Tems"}).id, sync.ensure_source().id


def test_one_snapshot_per_artist_source_metric_and_day(app):
    artist_id, source_id = ids()

    first = metric_service.record_snapshot(artist_id, source_id, "listeners", 1200, captured_at=NOON)
    assert first.value == 1200

    same_day = NOON + timedelta(hours=3)
    assert metric_service.record_snapshot(artist_id, source_id, "listeners", 1300, captured_at=same_day) is None
    assert metric_service.record_snapshot(artist_id, source_id, "playcount", 5, captured_at=same_day) is not None
    next_day = NOON + timedelta(days=1)
    assert metric_service.record_snapshot(artist_id, source_id, "listeners", 1350, captured_at=next_day) is not None


def test_zero_is_a_valid_value(app):
    artist_id, source_id = ids()
    assert metric_service.record_snapshot(artist_id, source_id, "listeners", 0, captured_at=NOON).value == 0


@pytest.mark.parametrize(
    "metric, value, captured_at",
    [
        ("listeners", -1, NOON),
        ("listeners", True, NOON),
        ("listeners", 12.5, NOON),
        ("Bad Name!", 5, NOON),
        ("listeners", 5, datetime(2026, 11, 18, 12, 0)),
    ],
)
def test_invalid_snapshots_are_rejected(app, metric, value, captured_at):
    artist_id, source_id = ids()
    with pytest.raises(ValidationError):
        metric_service.record_snapshot(artist_id, source_id, metric, value, captured_at=captured_at)