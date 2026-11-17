import sqlalchemy as sa
from flask import current_app, jsonify, render_template, send_from_directory
from sqlalchemy.exc import SQLAlchemyError

from app.errors import AppError
from app.extensions import db
from app.main import bp


@bp.after_request
def page_security_headers(response):
    """HTML pages may only load scripts, styles and images from this site."""
    if response.mimetype == "text/html":
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@bp.route("/")
def index():
    return jsonify(message="Nigerian Trends & Discovery Platform", status="running")


@bp.route("/health")
def health():
    return jsonify(status="ok")


@bp.route("/health/db")
def health_db():
    try:
        db.session.execute(sa.text("SELECT 1"))
    except SQLAlchemyError:
        current_app.logger.exception("Database health check failed")
        raise AppError(
            "Database unavailable.", status_code=503, code="database_unavailable"
        ) from None
    return jsonify(status="ok", database="up")


@bp.get("/media/<path:filename>")
def media(filename):
    """Serves uploaded images in development. Phase 14 replaces this with object storage."""
    response = send_from_directory(
        current_app.config["UPLOAD_DIR"], filename, max_age=60 * 60 * 24 * 30
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@bp.get("/artists/<slug>")
def artist_page(slug):
    return render_template("artist.html")


@bp.get("/songs/<int:song_id>")
def song_page(song_id):
    return render_template("song.html")


@bp.get("/search")
def search_page():
    return render_template("search.html")