import sqlalchemy as sa
from flask import current_app, jsonify, send_from_directory
from sqlalchemy.exc import SQLAlchemyError

from app.errors import AppError
from app.extensions import db
from app.main import bp


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