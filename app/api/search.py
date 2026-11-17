from flask import jsonify, request

from app.api import bp
from app.api.serializers import (
    serialize_album_summary,
    serialize_artist_summary,
    serialize_song_summary,
)
from app.extensions import limiter
from app.services import search_service
from app.utils.validation import parse_int


@bp.get("/search")
@limiter.limit("120 per minute")
def search():
    limit = parse_int(request.args.get("limit"), "limit", default=5, minimum=1, maximum=20)
    result = search_service.search(request.args.get("q"), limit)
    return jsonify(
        data={
            "artists": [serialize_artist_summary(a) for a in result["artists"]],
            "songs": [serialize_song_summary(s) for s in result["songs"]],
            "albums": [serialize_album_summary(a) for a in result["albums"]],
        },
        meta={"query": result["query"], "totals": result["totals"]},
    )