from flask import current_app, jsonify, request
from flask_login import current_user

from app.api import bp
from app.errors import NotFoundError, ValidationError
from app.radar.rules import DEFAULT_RULES
from app.security import admin_required
from app.services import artist_service, radar_service
from app.utils.pagination import get_pagination
from app.utils.validation import require_fields

ENTRY_FIELDS = ("status", "note", "expires_on")


def _iso(value):
    return value.isoformat() if value else None


def serialize_entry(entry, artist):
    return {
        "artist": {"id": artist.id, "name": artist.name, "slug": artist.slug},
        "status": entry.status,
        "note": entry.note,
        "expires_at": _iso(entry.expires_at),
        "updated_at": _iso(entry.updated_at),
    }


@bp.get("/admin/radar/explain/<int:artist_id>")
@admin_required
def admin_radar_explain(artist_id):
    artist, facts, evaluation = radar_service.explain(artist_id)
    return jsonify(
        data={
            "artist": {
                "id": artist.id,
                "name": artist.name,
                "slug": artist.slug,
                "archived": artist.archived_at is not None,
            },
            "appears": evaluation.appears,
            "eligible": evaluation.eligible,
            "score": evaluation.score,
            "min_score_to_appear": DEFAULT_RULES.min_score_to_appear,
            "editors_pick": evaluation.editors_pick,
            "overridden_checks": evaluation.overridden,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail} for c in evaluation.checks
            ],
            "components": [
                {"name": c.name, "points": c.points, "detail": c.detail}
                for c in evaluation.components
            ],
            "inputs": {
                "debut_year": facts.debut_year,
                "has_public_content": facts.has_public_content,
                "last_release_date": _iso(facts.last_release_date),
                "last_update_at": _iso(facts.last_update_at),
                "listeners_latest": facts.listeners_latest,
                "listeners_base": facts.listeners_base,
                "span_days": facts.span_days,
            },
        }
    )


@bp.get("/admin/radar/entries")
@admin_required
def admin_list_radar_entries():
    page, per_page = get_pagination(request.args)
    rows, total = radar_service.list_entries(request.args.get("status"), page, per_page)
    return jsonify(
        data=[serialize_entry(entry, artist) for entry, artist in rows],
        meta={"page": page, "per_page": per_page, "total": total},
    )


@bp.put("/admin/radar/entries/<int:artist_id>")
@admin_required
def admin_set_radar_entry(artist_id):
    artist = artist_service.get_artist_by_id(artist_id)
    data = request.get_json(silent=True)
    require_fields(data, ["status"])
    unknown = [key for key in data if key not in ENTRY_FIELDS]
    if unknown:
        raise ValidationError("Unknown fields.", details={k: "Unknown field." for k in unknown})
    entry = radar_service.set_entry(
        artist, data["status"], data.get("note"), data.get("expires_on"), user_id=current_user.id
    )
    current_app.logger.info(
        "admin=%s set radar entry '%s' for artist=%s", current_user.id, entry.status, artist.id
    )
    return jsonify(data=serialize_entry(entry, artist))


@bp.delete("/admin/radar/entries/<int:artist_id>")
@admin_required
def admin_clear_radar_entry(artist_id):
    artist = artist_service.get_artist_by_id(artist_id)
    if not radar_service.clear_entry(artist):
        raise NotFoundError("This artist has no Radar entry.")
    current_app.logger.info("admin=%s cleared radar entry for artist=%s", current_user.id, artist_id)
    return jsonify(data={"message": "Entry removed."})