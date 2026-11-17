from flask import jsonify

from app.api import bp
from app.api.serializers import serialize_album_detail
from app.services import album_service, link_service


@bp.get("/albums/<int:album_id>")
def get_album(album_id):
    album = album_service.get_album(album_id)
    links = link_service.list_links("album", album.id)
    return jsonify(data=serialize_album_detail(album, links=links))