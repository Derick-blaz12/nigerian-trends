import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.errors import ConflictError, NotFoundError, ValidationError
from app.extensions import db
from app.models import Artist, ArtistExternalId, CollectionRun, DataSource, MatchCandidate

CANDIDATE_STATUSES = ("pending", "confirmed", "rejected")


def list_candidates(status, page, per_page, session=None):
    session = session or db.session
    if status not in CANDIDATE_STATUSES:
        raise ValidationError(
            "status is invalid.",
            details={"status": "Must be one of: pending, confirmed, rejected."},
        )
    total = session.scalar(
        sa.select(sa.func.count()).select_from(MatchCandidate).where(MatchCandidate.status == status)
    )
    rows = session.execute(
        sa.select(MatchCandidate, Artist)
        .join(Artist, Artist.id == MatchCandidate.artist_id)
        .where(MatchCandidate.status == status)
        .order_by(MatchCandidate.id.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()
    return rows, total


def _get_open_candidate(candidate_id, session):
    candidate = session.get(MatchCandidate, candidate_id)
    if candidate is None or candidate.status == "no_match":
        raise NotFoundError("Candidate not found.")
    if candidate.status != "pending":
        raise ConflictError(f"This candidate is already {candidate.status}.")
    return candidate


def confirm_candidate(candidate_id, session=None):
    session = session or db.session
    candidate = _get_open_candidate(candidate_id, session)
    artist = session.get(Artist, candidate.artist_id)
    if artist.archived_at is not None:
        raise ConflictError("The artist is archived.")
    already = session.scalar(
        sa.select(ArtistExternalId.id).where(
            ArtistExternalId.artist_id == artist.id,
            ArtistExternalId.data_source_id == candidate.data_source_id,
        )
    )
    if already is not None:
        raise ConflictError("This artist is already linked to this source.")

    try:
        session.add(
            ArtistExternalId(
                artist_id=artist.id,
                data_source_id=candidate.data_source_id,
                external_id=candidate.external_id,
            )
        )
        candidate.status = "confirmed"
        session.execute(
            sa.update(MatchCandidate)
            .where(
                MatchCandidate.artist_id == artist.id,
                MatchCandidate.data_source_id == candidate.data_source_id,
                MatchCandidate.status == "pending",
                MatchCandidate.id != candidate.id,
            )
            .values(status="rejected")
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ConflictError("This external id is already linked to another artist.") from None
    return candidate, artist


def reject_candidate(candidate_id, session=None):
    session = session or db.session
    candidate = _get_open_candidate(candidate_id, session)
    candidate.status = "rejected"
    session.commit()
    return candidate, session.get(Artist, candidate.artist_id)


def list_runs(page, per_page, session=None):
    session = session or db.session
    total = session.scalar(sa.select(sa.func.count()).select_from(CollectionRun))
    rows = session.execute(
        sa.select(CollectionRun, DataSource.name)
        .join(DataSource, DataSource.id == CollectionRun.data_source_id)
        .order_by(CollectionRun.started_at.desc(), CollectionRun.id.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()
    return rows, total