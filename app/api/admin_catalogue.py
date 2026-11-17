from flask import current_app, jsonify, request
from flask_login import current_user

from app.api import bp
from app.api.serializers import (
    serialize_album_detail,
    serialize_album_summary,
    serialize_link,
    serialize_song_detail,
    serialize_song_summary,
)
from app.security import admin_required
from app.services import album_service, link_service, song_service
from app.utils.pagination import get_pagination
from app.utils.validation import parse_int


def _log(action, kind, item_id):
    current_app.logger.info("admin=%s %s %s=%s", current_user.id, action, kind, item_id)


def _song_response(song, status=200):
    links = link_service.list_links("song", song.id)
    response = jsonify(data=serialize_song_detail(song, admin=True, links=links))
    response.status_code = status
    return response


def _album_response(album, status=200):
    links = link_service.list_links("album", album.id)
    response = jsonify(data=serialize_album_detail(album, admin=True, links=links))
    response.status_code = status
    return response


# ---------- songs ----------

@bp.get("/admin/songs")
@admin_required
def admin_list_songs():
    page, per_page = get_pagination(request.args)
    items, total = song_service.list_songs(
        page,
        per_page,
        q=request.args.get("q"),
        genre=request.args.get("genre"),
        artist=request.args.get("artist"),
        status=request.args.get("status", "active"),
        public=False,
    )
    return jsonify(
        data=[serialize_song_summary(s, admin=True) for s in items],
        meta={"page": page, "per_page": per_page, "total": total},
    )


@bp.get("/admin/songs/<int:song_id>")
@admin_required
def admin_get_song(song_id):
    return _song_response(song_service.get_song(song_id, include_hidden=True))


@bp.post("/admin/songs")
@admin_required
def admin_create_song():
    song = song_service.create_song(request.get_json(silent=True))
    _log("created", "song", song.id)
    return _song_response(song, 201)


@bp.patch("/admin/songs/<int:song_id>")
@admin_required
def admin_update_song(song_id):
    song = song_service.get_song(song_id, include_hidden=True)
    song = song_service.update_song(song, request.get_json(silent=True))
    _log("updated", "song", song.id)
    return _song_response(song)


@bp.post("/admin/songs/<int:song_id>/archive")
@admin_required
def admin_archive_song(song_id):
    song = song_service.archive_song(song_service.get_song(song_id, include_hidden=True))
    _log("archived", "song", song.id)
    return _song_response(song)


@bp.post("/admin/songs/<int:song_id>/restore")
@admin_required
def admin_restore_song(song_id):
    song = song_service.restore_song(song_service.get_song(song_id, include_hidden=True))
    _log("restored", "song", song.id)
    return _song_response(song)


# ---------- albums ----------

@bp.get("/admin/albums")
@admin_required
def admin_list_albums():
    page, per_page = get_pagination(request.args)
    artist_id = parse_int(request.args.get("artist_id"), "artist_id", default=None)
    items, total = album_service.list_albums(
        page,
        per_page,
        q=request.args.get("q"),
        artist_id=artist_id,
        status=request.args.get("status", "active"),
    )
    return jsonify(
        data=[serialize_album_summary(a, admin=True) for a in items],
        meta={"page": page, "per_page": per_page, "total": total},
    )


@bp.get("/admin/albums/<int:album_id>")
@admin_required
def admin_get_album(album_id):
    return _album_response(album_service.get_album(album_id, include_hidden=True))


@bp.post("/admin/albums")
@admin_required
def admin_create_album():
    album = album_service.create_album(request.get_json(silent=True))
    _log("created", "album", album.id)
    return _album_response(album, 201)


@bp.patch("/admin/albums/<int:album_id>")
@admin_required
def admin_update_album(album_id):
    album = album_service.get_album(album_id, include_hidden=True)
    album = album_service.update_album(album, request.get_json(silent=True))
    _log("updated", "album", album.id)
    return _album_response(album)


@bp.post("/admin/albums/<int:album_id>/archive")
@admin_required
def admin_archive_album(album_id):
    album = album_service.archive_album(album_service.get_album(album_id, include_hidden=True))
    _log("archived", "album", album.id)
    return _album_response(album)


@bp.post("/admin/albums/<int:album_id>/restore")
@admin_required
def admin_restore_album(album_id):
    album = album_service.restore_album(album_service.get_album(album_id, include_hidden=True))
    _log("restored", "album", album.id)
    return _album_response(album)


# ---------- links ----------

def _create_link(target_type, target_id):
    link = link_service.add_link(target_type, target_id, request.get_json(silent=True))
    _log("added link to", target_type, target_id)
    return jsonify(data=serialize_link(link)), 201


@bp.post("/admin/artists/<int:artist_id>/links")
@admin_required
def admin_add_artist_link(artist_id):
    return _create_link("artist", artist_id)


@bp.post("/admin/songs/<int:song_id>/links")
@admin_required
def admin_add_song_link(song_id):
    return _create_link("song", song_id)


@bp.post("/admin/albums/<int:album_id>/links")
@admin_required
def admin_add_album_link(album_id):
    return _create_link("album", album_id)


@bp.delete("/admin/links/<int:link_id>")
@admin_required
def admin_delete_link(link_id):
    link_service.delete_link(link_id)
    _log("removed", "link", link_id)
    return jsonify(data={"message": "Link removed."})