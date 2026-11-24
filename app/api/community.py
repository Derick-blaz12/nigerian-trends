from flask import jsonify, request
from flask_login import current_user, login_required

from app.api import bp
from app.api.community_serializers import serialize_comment
from app.api.serializers import serialize_song_summary
from app.community.rules import COMMUNITY_VERSION, DEFAULT_RULES, rules_as_dict
from app.errors import ValidationError
from app.extensions import limiter
from app.security import user_or_ip_key
from app.services import comment_service, moderation_service, ranking_service, reaction_service
from app.utils.pagination import get_pagination
from app.utils.validation import parse_int, require_fields


def _me():
    return current_user._get_current_object()


def _object(data):
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object.")
    return data


# ---------- reactions ----------

@bp.get("/songs/<int:song_id>/community")
def song_community(song_id):
    viewer_id = current_user.id if current_user.is_authenticated else None
    response = jsonify(data=reaction_service.song_stats(song_id, viewer_id))
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.put("/songs/<int:song_id>/reactions/<kind>")
@login_required
@limiter.limit("60 per minute", key_func=user_or_ip_key)
def add_reaction(song_id, kind):
    changed = reaction_service.set_reaction(_me(), song_id, kind)
    return jsonify(data={"kind": kind, "active": True, "changed": changed})


@bp.delete("/songs/<int:song_id>/reactions/<kind>")
@login_required
@limiter.limit("60 per minute", key_func=user_or_ip_key)
def remove_reaction(song_id, kind):
    changed = reaction_service.remove_reaction(_me(), song_id, kind)
    return jsonify(data={"kind": kind, "active": False, "changed": changed})


# ---------- comments ----------

@bp.get("/songs/<int:song_id>/comments")
def list_song_comments(song_id):
    page, per_page = get_pagination(request.args)
    result = comment_service.list_comments(song_id, page, per_page)
    return jsonify(
        data=[
            serialize_comment(t["comment"], result["authors"], replies=t["replies"])
            for t in result["threads"]
        ],
        meta={"page": page, "per_page": per_page, "total": result["total"]},
    )


@bp.post("/songs/<int:song_id>/comments")
@login_required
@limiter.limit("5 per minute; 30 per hour", key_func=user_or_ip_key)
def create_comment(song_id):
    user = _me()
    comment = comment_service.create_comment(user, song_id, request.get_json(silent=True))
    return jsonify(data=serialize_comment(comment, {user.id: user.username})), 201


@bp.patch("/comments/<int:comment_id>")
@login_required
@limiter.limit("20 per minute", key_func=user_or_ip_key)
def edit_comment(comment_id):
    user = _me()
    comment = comment_service.edit_comment(user, comment_id, request.get_json(silent=True))
    return jsonify(data=serialize_comment(comment, {user.id: user.username}))


@bp.delete("/comments/<int:comment_id>")
@login_required
@limiter.limit("20 per minute", key_func=user_or_ip_key)
def delete_comment(comment_id):
    comment_service.delete_comment(_me(), comment_id)
    return jsonify(data={"message": "Comment deleted."})


@bp.post("/comments/<int:comment_id>/report")
@login_required
@limiter.limit("10 per hour", key_func=user_or_ip_key)
def report_comment(comment_id):
    data = _object(request.get_json(silent=True))
    require_fields(data, ["reason"])
    unknown = [key for key in data if key not in ("reason", "details")]
    if unknown:
        raise ValidationError("Unknown fields.", details={k: "Unknown field." for k in unknown})
    moderation_service.report_comment(_me(), comment_id, data["reason"], data.get("details"))
    return jsonify(data={"message": "Thank you. A moderator will take a look."}), 201


# ---------- discovery ----------

@bp.get("/rankings/songs")
def song_rankings():
    period = request.args.get("period", "trending")
    limit = parse_int(request.args.get("limit"), "limit", default=20, minimum=1, maximum=50)
    items, total = ranking_service.song_rankings(period, limit, genre=request.args.get("genre"))
    data = [
        {
            "rank": rank,
            "song": serialize_song_summary(item["song"]),
            "community": {
                "score": item["score"],
                "likes": item["likes"],
                "recommends": item["recommends"],
                "commenters": item["commenters"],
                "engaged_users": item["engaged_users"],
            },
        }
        for rank, item in enumerate(items, start=1)
    ]
    response = jsonify(
        data=data,
        meta={
            "period": period,
            "total": total,
            "source": "community",
            "rules_version": COMMUNITY_VERSION,
            "note": "Based on activity on this site only. These are not streaming numbers.",
        },
    )
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


@bp.get("/discussions/recent")
def recent_discussions():
    page, per_page = get_pagination(request.args)
    result = comment_service.recent_comments(page, per_page)
    return jsonify(
        data=[
            {
                "comment": serialize_comment(comment, result["authors"]),
                "song": serialize_song_summary(song),
            }
            for comment, song in result["items"]
        ],
        meta={"page": page, "per_page": per_page, "total": result["total"]},
    )


@bp.get("/community/rules")
def community_rules():
    return jsonify(data={"version": COMMUNITY_VERSION, "rules": rules_as_dict(DEFAULT_RULES)})