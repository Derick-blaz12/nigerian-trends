from flask import current_app, jsonify, request
from flask_login import current_user

from app.api import bp
from app.api.serializers import serialize_update_detail, serialize_update_summary
from app.security import admin_required
from app.services import update_service
from app.utils.pagination import get_pagination
from app.utils.validation import parse_int


def _log(action, update):
    current_app.logger.info("admin=%s %s update=%s", current_user.id, action, update.id)


def _response(update, status=200):
    response = jsonify(data=serialize_update_detail(update, admin=True))
    response.status_code = status
    return response


def _load(update_id):
    return update_service.get_update(update_id, include_hidden=True)


@bp.get("/admin/editorial/summary")
@admin_required
def admin_editorial_summary():
    return jsonify(data=update_service.count_by_status())


@bp.get("/admin/updates")
@admin_required
def admin_list_updates():
    page, per_page = get_pagination(request.args)
    artist_id = parse_int(request.args.get("artist_id"), "artist_id", default=None)
    items, total = update_service.list_updates(
        page,
        per_page,
        public=False,
        q=request.args.get("q"),
        status=request.args.get("status", "all"),
        artist=request.args.get("artist"),
        artist_id=artist_id,
        category=request.args.get("category"),
    )
    return jsonify(
        data=[serialize_update_summary(u, admin=True) for u in items],
        meta={"page": page, "per_page": per_page, "total": total},
    )


@bp.get("/admin/updates/<int:update_id>")
@admin_required
def admin_get_update(update_id):
    return _response(_load(update_id))


@bp.post("/admin/updates")
@admin_required
def admin_create_update():
    update = update_service.create_update(request.get_json(silent=True), author_id=current_user.id)
    _log("created", update)
    return _response(update, 201)


@bp.patch("/admin/updates/<int:update_id>")
@admin_required
def admin_edit_update(update_id):
    update = update_service.update_update(_load(update_id), request.get_json(silent=True))
    _log("edited", update)
    return _response(update)


@bp.post("/admin/updates/<int:update_id>/publish")
@admin_required
def admin_publish_update(update_id):
    update = update_service.publish_update(_load(update_id))
    _log("published", update)
    return _response(update)


@bp.post("/admin/updates/<int:update_id>/unpublish")
@admin_required
def admin_unpublish_update(update_id):
    update = update_service.unpublish_update(_load(update_id))
    _log("unpublished", update)
    return _response(update)


@bp.post("/admin/updates/<int:update_id>/archive")
@admin_required
def admin_archive_update(update_id):
    update = update_service.archive_update(_load(update_id))
    _log("archived", update)
    return _response(update)


@bp.post("/admin/updates/<int:update_id>/restore")
@admin_required
def admin_restore_update(update_id):
    update = update_service.restore_update(_load(update_id))
    _log("restored", update)
    return _response(update)