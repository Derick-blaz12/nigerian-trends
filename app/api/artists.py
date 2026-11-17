from flask import jsonify, request

from app.api import bp
from app.api.serializers import serialize_artist_detail, serialize_artist_summary
from app.services import artist_service, link_service
from app.utils.pagination import get_pagination


@bp.get("/artists")
def list_artists():
    page, per_page = get_pagination(request.args)
    items, total = artist_service.list_artists(
        page, per_page, q=request.args.get("q"), genre=request.args.get("genre")
    )
    return jsonify(
        data=[serialize_artist_summary(a) for a in items],
        meta={"page": page, "per_page": per_page, "total": total},
    )


@bp.get("/artists/<slug>")
def get_artist(slug):
    artist = artist_service.get_artist_by_slug(slug)
    links = link_service.list_links("artist", artist.id)
    return jsonify(data=serialize_artist_detail(artist, links=links))