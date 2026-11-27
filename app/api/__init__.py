from flask import Blueprint, request

bp = Blueprint("api", __name__, url_prefix="/api/v1")


@bp.after_request
def no_store_for_private_routes(response):
    """Browsers and proxies must never cache account, personal or admin responses."""
    if request.path.startswith(("/api/v1/auth", "/api/v1/admin", "/api/v1/me")):
        response.headers["Cache-Control"] = "no-store"
    return response


from app.api import (  # noqa: E402,F401
    admin, admin_artists, admin_catalogue, admin_collection, admin_moderation, admin_radar,
    admin_updates, albums, artists, auth, community, following, genres, radar, search, songs,
    updates,
)