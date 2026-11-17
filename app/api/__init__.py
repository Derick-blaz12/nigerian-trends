from flask import Blueprint, request

bp = Blueprint("api", __name__, url_prefix="/api/v1")


@bp.after_request
def no_store_for_private_routes(response):
    """Browsers and proxies must never cache account or admin responses."""
    if request.path.startswith(("/api/v1/auth", "/api/v1/admin")):
        response.headers["Cache-Control"] = "no-store"
    return response


from app.api import admin, auth, genres  # noqa: E402,F401