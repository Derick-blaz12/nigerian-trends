import io

import pytest
from flask import g
from PIL import Image

from app import create_app
from app.extensions import db
from app.services import auth_service

PASSWORD = "correct-horse-battery"


@pytest.fixture
def app(tmp_path):
    app = create_app("testing", {"UPLOAD_DIR": str(tmp_path / "uploads")})
    uri = app.config["SQLALCHEMY_DATABASE_URI"] or ""
    assert uri.endswith("_test"), "Refusing to run tests against a non-test database"

    @app.before_request
    def reset_login_cache():
        # Tests keep one app context open, so Flask's `g` would otherwise
        # leak the logged-in user from one test client to the next.
        g.pop("_login_user", None)

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def _logged_in_client(app, email, username, role):
    user = auth_service.register_user(email, username, PASSWORD)
    user.role = role
    db.session.commit()
    test_client = app.test_client()
    response = test_client.post(
        "/api/v1/auth/login", json={"identifier": username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return test_client


@pytest.fixture
def admin_client(app):
    return _logged_in_client(app, "boss@example.com", "boss_user", "admin")


@pytest.fixture
def user_client(app):
    return _logged_in_client(app, "fan@example.com", "fan_user", "user")


@pytest.fixture
def make_image():
    def _make(size=(400, 400), fmt="PNG", mode="RGB", color=(200, 30, 30)):
        buffer = io.BytesIO()
        Image.new(mode, size, color).save(buffer, format=fmt)
        return buffer.getvalue()

    return _make