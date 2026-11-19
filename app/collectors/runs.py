from datetime import timedelta

import sqlalchemy as sa

from app.collectors.http import CollectorError
from app.extensions import db
from app.models import CollectionRun
from app.models.mixins import utcnow

STALE_RUN_HOURS = 2


class RunAlreadyActive(CollectorError):
    """Another run of the same job is still in progress."""


class Counters:
    def __init__(self):
        self.seen = self.created = self.updated = self.skipped = self.failed = 0
        self.errors = []

    def error(self, message):
        self.failed += 1
        if len(self.errors) < 20:
            self.errors.append(message)


def start_run(source, job, triggered_by="cli", session=None):
    session = session or db.session
    running = session.scalars(
        sa.select(CollectionRun).where(
            CollectionRun.data_source_id == source.id,
            CollectionRun.job == job,
            CollectionRun.status == "running",
        )
    ).all()
    cutoff = utcnow() - timedelta(hours=STALE_RUN_HOURS)
    for run in running:
        if run.started_at < cutoff:
            run.status = "failed"
            run.finished_at = utcnow()
            run.error_summary = "Marked failed: the run never finished."
    session.commit()
    if any(run.status == "running" for run in running):
        raise RunAlreadyActive(f"A {job} run is already in progress.")

    run = CollectionRun(data_source_id=source.id, job=job, triggered_by=triggered_by)
    session.add(run)
    session.commit()
    return run


def finish_run(run, status, counters, requests_made, note=None, session=None):
    session = session or db.session
    run.status = status
    run.finished_at = utcnow()
    run.requests_made = requests_made
    run.items_seen = counters.seen
    run.items_created = counters.created
    run.items_updated = counters.updated
    run.items_skipped = counters.skipped
    run.items_failed = counters.failed
    lines = ([note] if note else []) + counters.errors
    run.error_summary = "\n".join(lines)[:4000] or None
    session.commit()