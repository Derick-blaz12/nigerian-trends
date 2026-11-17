from flask import jsonify, request, session
from flask_login import current_user, login_required, login_user, logout_user
from flask_wtf.csrf import generate_csrf

from app.api import bp
from app.extensions import limiter
from app.services import auth_service
from app.utils.validation import require_fields


def serialize_user(user):
    """Never include password_hash here."""
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@bp.get("/auth/csrf")
def get_csrf_token():
    return jsonify(data={"csrf_token": generate_csrf()})


@bp.post("/auth/register")
@limiter.limit("20 per hour")
def register():
    data = request.get_json(silent=True)
    require_fields(data, ["email", "username", "password"])
    user = auth_service.register_user(data["email"], data["username"], data["password"])
    login_user(user)
    session.permanent = True
    return jsonify(data=serialize_user(user)), 201


@bp.post("/auth/login")
@limiter.limit("10 per minute")
def login():
    data = request.get_json(silent=True)
    require_fields(data, ["identifier", "password"])
    user = auth_service.authenticate(data["identifier"], data["password"])
    login_user(user)
    session.permanent = True
    return jsonify(data=serialize_user(user))


@bp.post("/auth/logout")
@login_required
def logout():
    logout_user()
    return jsonify(data={"message": "Logged out."})


@bp.get("/auth/me")
@login_required
def me():
    return jsonify(data=serialize_user(current_user))