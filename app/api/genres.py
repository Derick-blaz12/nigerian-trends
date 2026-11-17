from flask import jsonify, request

from app.api import bp
from app.services import genre_service
from app.utils.pagination import get_pagination


def serialize_genre(genre):
    return {"id": genre.id, "name": genre.name, "slug": genre.slug}


@bp.get("/genres")
def list_genres():
    page, per_page = get_pagination(request.args)
    items, total = genre_service.list_genres(page, per_page)
    return jsonify(
        data=[serialize_genre(g) for g in items],
        meta={"page": page, "per_page": per_page, "total": total},
    )


@bp.get("/genres/<slug>")
def get_genre(slug):
    return jsonify(data=serialize_genre(genre_service.get_genre_by_slug(slug)))