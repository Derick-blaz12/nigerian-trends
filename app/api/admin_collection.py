from flask import current_app, jsonify, request
from flask_login import current_user

from app.api import bp
from app.security import admin_required
from app.services import collection_service
from app.utils.pagination import get_pagination


def _iso(value):
    return value.isoformat() if value else None


def serialize_candidate(candidate, artist):
    return {
        "id": candidate.id,
        "status": candidate.status,
        "score": candidate.score,
        "artist": {"id": artist.id, "name": artist.name, "slug": artist.slug},
        "candidate": {
            "musicbrainz_id": candidate.external_id,
            "name": candidate.external_name,
            "country": candidate.country,
            "disambiguation": candidate.disambiguation,
            "begin_year": candidate.begin_year,
            "url": f"https://musicbrainz.org/artist/{candidate.external_id}",
        },
    }


def serialize_run(run, source_name):
    return {
        "id": run.id,
        "source": source_name,
        "job": run.job,
        "status": run.status,
        "triggered_by": run.triggered_by,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "requests_made": run.requests_made,
        "items": {
            "seen": run.items_seen,
            "created": run.items_created,
            "updated": run.items_updated,
            "skipped": run.items_skipped,
            "failed": run.items_failed,
        },
        "error_summary": run.error_summary,
    }


def _log(action, candidate_id):
    current_app.logger.info("admin=%s %s match-candidate=%s", current_user.id, action, candidate_id)


@bp.get("/admin/match-candidates")
@admin_required
def admin_list_candidates():
    page, per_page = get_pagination(request.args)
    rows, total = collection_service.list_candidates(
        request.args.get("status", "pending"), page, per_page
    )
    return jsonify(
        data=[serialize_candidate(c, a) for c, a in rows],
        meta={"page": page, "per_page": per_page, "total": total},
    )


@bp.post("/admin/match-candidates/<int:candidate_id>/confirm")
@admin_required
def admin_confirm_candidate(candidate_id):
    candidate, artist = collection_service.confirm_candidate(candidate_id)
    _log("confirmed", candidate_id)
    return jsonify(data=serialize_candidate(candidate, artist))


@bp.post("/admin/match-candidates/<int:candidate_id>/reject")
@admin_required
def admin_reject_candidate(candidate_id):
    candidate, artist = collection_service.reject_candidate(candidate_id)
    _log("rejected", candidate_id)
    return jsonify(data=serialize_candidate(candidate, artist))


@bp.get("/admin/collection-runs")
@admin_required
def admin_list_runs():
    page, per_page = get_pagination(request.args)
    rows, total = collection_service.list_runs(page, per_page)
    return jsonify(
        data=[serialize_run(run, name) for run, name in rows],
        meta={"page": page, "per_page": per_page, "total": total},
    )