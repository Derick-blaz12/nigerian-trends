from flask import jsonify, request

from app.api import bp
from app.api.serializers import serialize_song_detail, serialize_song_summary
from app.services import link_service, song_service
from app.utils.pagination import get_pagination


@bp.get("/songs")
def list_songs():
    page, per_page = get_pagination(request.args)
    items, total = song_service.list_songs(
        page,
        per_page,
        q=request.args.get("q"),
        genre=request.args.get("genre"),
        artist=request.args.get("artist"),
    )
    return jsonify(
        data=[serialize_song_summary(s) for s in items],
        meta={"page": page, "per_page": per_page, "total": total},
    )


@bp.get("/songs/<int:song_id>")
def get_song(song_id):
    song = song_service.get_song(song_id)
    links = link_service.list_links("song", song.id)
    return jsonify(data=serialize_song_detail(song, links=links))