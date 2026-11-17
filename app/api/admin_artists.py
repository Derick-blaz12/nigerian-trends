from flask import current_app, jsonify, request
from flask_login import current_user

from app.api import bp
from app.api.serializers import serialize_artist_detail, serialize_artist_summary
from app.errors import ValidationError
from app.security import admin_required
from app.services import artist_service, link_service
from app.utils.pagination import get_pagination
from app.utils.validation import require_fields


def _log(action, artist):
    current_app.logger.info(
        "admin=%s %s artist=%s (%s)", current_user.id, action, artist.id, artist.slug
    )


def _detail(artist):
    links = link_service.list_links("artist", artist.id)
    return jsonify(data=serialize_artist_detail(artist, admin=True, links=links))

@bp.get("/admin/artists")
@admin_required
def admin_list_artists():
    page, per_page = get_pagination(request.args)
    items, total = artist_service.list_artists(
        page,
        per_page,
        q=request.args.get("q"),
        genre=request.args.get("genre"),
        status=request.args.get("status", "active"),
    )
    return jsonify(
        data=[serialize_artist_summary(a, admin=True) for a in items],
        meta={"page": page, "per_page": per_page, "total": total},
    )


@bp.get("/admin/artists/<int:artist_id>")
@admin_required
def admin_get_artist(artist_id):
    return _detail(artist_service.get_artist_by_id(artist_id))


@bp.post("/admin/artists")
@admin_required
def admin_create_artist():
    data = request.get_json(silent=True)
    require_fields(data, ["name"])
    artist = artist_service.create_artist(data)
    _log("created", artist)
    response = _detail(artist)
    response.status_code = 201
    return response


@bp.patch("/admin/artists/<int:artist_id>")
@admin_required
def admin_update_artist(artist_id):
    artist = artist_service.get_artist_by_id(artist_id)
    artist = artist_service.update_artist(artist, request.get_json(silent=True))
    _log("updated", artist)
    return _detail(artist)


@bp.post("/admin/artists/<int:artist_id>/archive")
@admin_required
def admin_archive_artist(artist_id):
    artist = artist_service.archive_artist(artist_service.get_artist_by_id(artist_id))
    _log("archived", artist)
    return _detail(artist)


@bp.post("/admin/artists/<int:artist_id>/restore")
@admin_required
def admin_restore_artist(artist_id):
    artist = artist_service.restore_artist(artist_service.get_artist_by_id(artist_id))
    _log("restored", artist)
    return _detail(artist)


@bp.post("/admin/artists/<int:artist_id>/image")
@admin_required
def admin_upload_artist_image(artist_id):
    artist = artist_service.get_artist_by_id(artist_id)
    upload = request.files.get("image")
    if upload is None or not upload.filename:
        raise ValidationError(
            "An image file is required.",
            details={"image": "Attach a file in the 'image' form field."},
        )
    data = upload.read(current_app.config["MAX_IMAGE_BYTES"] + 1)
    artist = artist_service.set_artist_image(artist, data)
    _log("uploaded image for", artist)
    return _detail(artist)


@bp.delete("/admin/artists/<int:artist_id>/image")
@admin_required
def admin_delete_artist_image(artist_id):
    artist = artist_service.remove_artist_image(artist_service.get_artist_by_id(artist_id))
    _log("removed image from", artist)
    return _detail(artist)