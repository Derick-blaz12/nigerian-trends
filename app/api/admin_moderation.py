from flask import current_app, jsonify, request
from flask_login import current_user

from app.api import bp
from app.api.community_serializers import serialize_comment, serialize_queue_item
from app.errors import ValidationError
from app.extensions import db
from app.models import User
from app.security import admin_required
from app.services import moderation_service
from app.utils.pagination import get_pagination
from app.utils.validation import require_fields


def _admin():
    return current_user._get_current_object()


def _optional_object(allowed):
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object.")
    unknown = [key for key in data if key not in allowed]
    if unknown:
        raise ValidationError("Unknown fields.", details={k: "Unknown field." for k in unknown})
    return data


def _comment_response(comment):
    author = db.session.get(User, comment.user_id)
    authors = {comment.user_id: author.username} if author else {}
    return jsonify(data=serialize_comment(comment, authors, admin=True))


def _user_response(user):
    return jsonify(
        data={
            "id": user.id,
            "username": user.username,
            "muted_until": user.muted_until.isoformat() if user.muted_until else None,
        }
    )


def _log(action, kind, item_id):
    current_app.logger.info("admin=%s %s %s=%s", current_user.id, action, kind, item_id)


@bp.get("/admin/moderation/queue")
@admin_required
def admin_moderation_queue():
    page, per_page = get_pagination(request.args)
    items, total = moderation_service.report_queue(page, per_page)
    return jsonify(
        data=[serialize_queue_item(item) for item in items],
        meta={"page": page, "per_page": per_page, "total": total},
    )


@bp.post("/admin/moderation/comments/<int:comment_id>/remove")
@admin_required
def admin_remove_comment(comment_id):
    data = _optional_object(("note",))
    comment = moderation_service.remove_comment(_admin(), comment_id, note=data.get("note"))
    _log("removed", "comment", comment_id)
    return _comment_response(comment)


@bp.post("/admin/moderation/comments/<int:comment_id>/restore")
@admin_required
def admin_restore_comment(comment_id):
    comment = moderation_service.restore_comment(_admin(), comment_id)
    _log("restored", "comment", comment_id)
    return _comment_response(comment)


@bp.post("/admin/moderation/comments/<int:comment_id>/dismiss")
@admin_required
def admin_dismiss_reports(comment_id):
    comment = moderation_service.dismiss_reports(_admin(), comment_id)
    _log("dismissed reports on", "comment", comment_id)
    return _comment_response(comment)


@bp.post("/admin/moderation/users/<int:user_id>/mute")
@admin_required
def admin_mute_user(user_id):
    data = _optional_object(("days",))
    require_fields(data, ["days"])
    user = moderation_service.mute_user(_admin(), user_id, data["days"])
    _log("muted", "user", user_id)
    return _user_response(user)


@bp.post("/admin/moderation/users/<int:user_id>/unmute")
@admin_required
def admin_unmute_user(user_id):
    user = moderation_service.unmute_user(user_id)
    _log("unmuted", "user", user_id)
    return _user_response(user)