from flask import jsonify, request
from flask_login import current_user, login_required

from app.api import bp
from app.api.follow_serializers import (
    serialize_feed_item,
    serialize_followed_artist,
    serialize_notification,
)
from app.errors import ValidationError
from app.extensions import limiter
from app.following.rules import DEFAULT_RULES, FOLLOW_VERSION, rules_as_dict
from app.security import user_or_ip_key
from app.services import (
    digest_service,
    feed_service,
    follow_service,
    notification_service,
    preference_service,
)
from app.utils.pagination import get_pagination


def _me():
    return current_user._get_current_object()


def _notify_from_body():
    """The optional {"notify": true|false} body of a follow request."""
    data = request.get_json(silent=True)
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object.")
    unknown = [key for key in data if key != "notify"]
    if unknown:
        raise ValidationError("Unknown fields.", details={k: "Unknown field." for k in unknown})
    return data.get("notify")


def _flag(name):
    """?name=true|false|1|0, or None when it isn't given."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise ValidationError(f"{name} is invalid.", details={name: "Use true or false."})


# ---------- following an artist ----------

@bp.get("/artists/<slug>/follow")
def follow_status(slug):
    viewer_id = current_user.id if current_user.is_authenticated else None
    response = jsonify(data=follow_service.follow_status(slug, viewer_id))
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.put("/artists/<slug>/follow")
@login_required
@limiter.limit("60 per minute", key_func=user_or_ip_key)
def follow(slug):
    row, changed = follow_service.follow_artist(_me(), slug, notify=_notify_from_body())
    return jsonify(data={"following": True, "notify": bool(row.notify), "changed": changed})


@bp.delete("/artists/<slug>/follow")
@login_required
@limiter.limit("60 per minute", key_func=user_or_ip_key)
def unfollow(slug):
    changed = follow_service.unfollow_artist(_me(), slug)
    return jsonify(data={"following": False, "notify": False, "changed": changed})


# ---------- the signed-in person's own data ----------

@bp.get("/me/following")
@login_required
def my_following():
    page, per_page = get_pagination(request.args)
    rows, total = follow_service.list_following(_me(), page, per_page)
    return jsonify(
        data=[serialize_followed_artist(follow_row, artist) for follow_row, artist in rows],
        meta={"page": page, "per_page": per_page, "total": total},
    )


@bp.get("/me/feed")
@login_required
def my_feed():
    page, per_page = get_pagination(request.args)
    items, total = feed_service.feed_items(_me(), page, per_page)
    return jsonify(
        data=[serialize_feed_item(item) for item in items],
        meta={"page": page, "per_page": per_page, "total": total},
    )


@bp.get("/me/notifications")
@login_required
def my_notifications():
    page, per_page = get_pagination(request.args)
    user = _me()
    items, total = notification_service.list_notifications(
        user, page, per_page, unread_only=bool(_flag("unread"))
    )
    return jsonify(
        data=[serialize_notification(item) for item in items],
        meta={
            "page": page,
            "per_page": per_page,
            "total": total,
            "unread": notification_service.unread_count(user),
        },
    )


@bp.get("/me/notifications/unread-count")
@login_required
def my_unread_count():
    return jsonify(data={"count": notification_service.unread_count(_me())})


@bp.post("/me/notifications/<int:notification_id>/read")
@login_required
@limiter.limit("120 per minute", key_func=user_or_ip_key)
def read_notification(notification_id):
    notification = notification_service.mark_read(_me(), notification_id)
    return jsonify(data={"id": notification.id, "read": True})


@bp.post("/me/notifications/read-all")
@login_required
@limiter.limit("30 per minute", key_func=user_or_ip_key)
def read_all_notifications():
    return jsonify(data={"marked": notification_service.mark_all_read(_me())})


@bp.get("/me/notification-preferences")
@login_required
def get_notification_preferences():
    return jsonify(data=preference_service.get_preferences(_me()))


@bp.patch("/me/notification-preferences")
@login_required
@limiter.limit("30 per minute", key_func=user_or_ip_key)
def update_notification_preferences():
    return jsonify(
        data=preference_service.update_preferences(_me(), request.get_json(silent=True))
    )


@bp.get("/me/digest-preview")
@login_required
def digest_preview():
    user = _me()
    return jsonify(
        data={
            "email_digest_enabled": preference_service.get_preferences(user)["email_digest"],
            "preview": digest_service.build_digest(user),
        },
        meta={"note": "Preview only. Emails are not sent yet."},
    )


@bp.get("/follow/rules")
def follow_rules():
    return jsonify(data={"version": FOLLOW_VERSION, "rules": rules_as_dict(DEFAULT_RULES)})