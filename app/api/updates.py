from flask import jsonify, request

from app.api import bp
from app.api.serializers import serialize_update_detail, serialize_update_summary
from app.services import update_service
from app.utils.pagination import get_pagination
from app.utils.validation import parse_int


@bp.get("/updates")
def list_updates():
    page, per_page = get_pagination(request.args)
    song_id = parse_int(request.args.get("song"), "song", default=None)
    album_id = parse_int(request.args.get("album"), "album", default=None)
    items, total = update_service.list_updates(
        page,
        per_page,
        public=True,
        artist=request.args.get("artist"),
        category=request.args.get("category"),
        song_id=song_id,
        album_id=album_id,
    )
    return jsonify(
        data=[serialize_update_summary(u) for u in items],
        meta={"page": page, "per_page": per_page, "total": total},
    )


@bp.get("/updates/<int:update_id>")
def get_update(update_id):
    return jsonify(data=serialize_update_detail(update_service.get_update(update_id)))