from functools import wraps

from flask import request
from flask_limiter.util import get_remote_address
from flask_login import current_user

from app.errors import AppError, AuthenticationError, ForbiddenError
from app.extensions import db, login_manager
from app.models import User


def register_request_limits(app):
    """JSON bodies are capped at MAX_JSON_BYTES; uploads get the larger global ceiling."""

    @app.before_request
    def limit_json_body():
        length = request.content_length
        if request.is_json and length is not None and length > app.config["MAX_JSON_BYTES"]:
            raise AppError("Request body too large.", status_code=413, code="payload_too_large")


@login_manager.user_loader
def load_user(user_id):
    """Runs on every request that carries a session cookie."""
    try:
        user = db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None
    # A disabled account loses its session immediately.
    return user if user is not None and user.is_active else None


@login_manager.unauthorized_handler
def handle_unauthorized():
    raise AuthenticationError("Authentication required.")


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            raise AuthenticationError("Authentication required.")
        if not current_user.is_admin:
            raise ForbiddenError("Administrator access required.")
        return view(*args, **kwargs)

    return wrapper


def user_or_ip_key():
    """Rate-limit signed-in people by account and everyone else by IP address.

    Many mobile users share one carrier IP, so limiting signed-in people by IP
    would punish innocent neighbours.
    """
    if current_user.is_authenticated:
        return f"user:{current_user.id}"
    return get_remote_address()