import sqlalchemy as sa
import pytest

from app import create_app
from app.extensions import db
from app.models import User
from app.services import auth_service

PASSWORD = "correct-horse-battery"


def register(client, **overrides):
    payload = {"email": "ade@example.com", "username": "ade_music", "password": PASSWORD}
    payload.update(overrides)
    return client.post("/api/v1/auth/register", json=payload)


def login(client, identifier, password=PASSWORD):
    return client.post(
        "/api/v1/auth/login", json={"identifier": identifier, "password": password}
    )


def get_user(email):
    return db.session.scalar(sa.select(User).where(User.email == email))


@pytest.fixture
def limited_client():
    """An app with rate limiting switched on."""
    app = create_app("testing", {"RATELIMIT_ENABLED": True})
    uri = app.config["SQLALCHEMY_DATABASE_URI"] or ""
    assert uri.endswith("_test"), "Refusing to run tests against a non-test database"
    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


def test_register_creates_user_and_logs_in(client):
    response = register(client)
    body = response.get_json()["data"]

    assert response.status_code == 201
    assert body["username"] == "ade_music"
    assert body["role"] == "user"
    assert "password" not in body and "password_hash" not in body

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.get_json()["data"]["email"] == "ade@example.com"


def test_register_normalizes_email_and_username(client):
    response = register(client, email="  Ade@Example.COM ", username="Ade_Music")
    assert response.status_code == 201
    user = get_user("ade@example.com")
    assert user is not None
    assert user.username == "ade_music"


def test_password_is_stored_hashed(client):
    register(client)
    user = get_user("ade@example.com")
    assert user.password_hash != PASSWORD
    assert user.check_password(PASSWORD)
    assert not user.check_password("some-other-password")


def test_register_ignores_client_supplied_role(client):
    response = register(client, role="admin", is_active=False)
    assert response.status_code == 201
    user = get_user("ade@example.com")
    assert user.role == "user"
    assert user.is_active is True


def test_duplicate_email_rejected(client):
    register(client)
    response = register(client, username="someone_else")
    assert response.status_code == 409
    assert "email" in response.get_json()["error"]["details"]


def test_duplicate_username_rejected_case_insensitively(client):
    register(client)
    response = register(client, email="other@example.com", username="ADE_MUSIC")
    assert response.status_code == 409
    assert "username" in response.get_json()["error"]["details"]


def test_short_password_rejected(client):
    response = register(client, password="short1")
    assert response.status_code == 422
    assert "password" in response.get_json()["error"]["details"]


def test_common_password_rejected(client):
    response = register(client, password="password123")
    assert response.status_code == 422


def test_invalid_usernames_rejected(client):
    for bad in ["ab", "has space", "admin", "x" * 31, "bad!name"]:
        assert register(client, username=bad).status_code == 422, bad


def test_missing_or_malformed_input_rejected(client):
    url = "/api/v1/auth/register"

    not_json = client.post(url, data="not json", content_type="application/json")
    assert not_json.status_code == 422

    missing = client.post(url, json={"email": "a@example.com"})
    assert missing.status_code == 422
    assert set(missing.get_json()["error"]["details"]) == {"username", "password"}

    assert register(client, email="not-an-email").status_code == 422
    assert register(client, email=["a@example.com"]).status_code == 422


def test_login_with_email_or_username(client):
    register(client)
    client.post("/api/v1/auth/logout")
    assert login(client, "ade@example.com").status_code == 200
    client.post("/api/v1/auth/logout")
    assert login(client, "ADE_MUSIC").status_code == 200


def test_login_updates_last_login_at(client):
    register(client)
    client.post("/api/v1/auth/logout")
    assert get_user("ade@example.com").last_login_at is None

    login(client, "ade_music")
    db.session.expire_all()
    assert get_user("ade@example.com").last_login_at is not None


def test_wrong_password_and_unknown_user_look_identical(client):
    register(client)
    client.post("/api/v1/auth/logout")

    wrong = login(client, "ade_music", "wrong-password-1")
    unknown = login(client, "ghost_user", "wrong-password-1")

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.get_json() == unknown.get_json()


def test_disabled_account_loses_access(client):
    register(client)  # logged in after registering
    user = get_user("ade@example.com")
    user.is_active = False
    db.session.commit()

    # The existing session stops working immediately...
    assert client.get("/api/v1/auth/me").status_code == 401
    # ...and a fresh login is refused with a clear reason.
    response = login(client, "ade_music")
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "account_disabled"


def test_logout_ends_session(client):
    register(client)
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_requires_login(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "unauthorized"


def test_admin_users_endpoint_permissions(app, client):
    url = "/api/v1/admin/users"
    assert client.get(url).status_code == 401  # anonymous

    register(client)  # regular user, logged in
    assert client.get(url).status_code == 403

    boss = auth_service.register_user("boss@example.com", "boss_user", PASSWORD)
    boss.role = "admin"
    db.session.commit()

    admin_client = app.test_client()
    assert login(admin_client, "boss_user").status_code == 200
    response = admin_client.get(url)
    assert response.status_code == 200
    assert response.get_json()["meta"]["total"] == 2


def test_csrf_enforced_when_enabled(app, client):
    app.config["WTF_CSRF_ENABLED"] = True
    payload = {"email": "ade@example.com", "username": "ade_music", "password": PASSWORD}
    url = "/api/v1/auth/register"

    assert client.post(url, json=payload).status_code == 400  # no token

    token = client.get("/api/v1/auth/csrf").get_json()["data"]["csrf_token"]
    response = client.post(url, json=payload, headers={"X-CSRFToken": token})
    assert response.status_code == 201


def test_login_is_rate_limited(limited_client):
    payload = {"identifier": "nobody", "password": "wrong-password-1"}
    statuses = [
        limited_client.post("/api/v1/auth/login", json=payload).status_code
        for _ in range(12)
    ]
    assert statuses[:10] == [401] * 10
    assert 429 in statuses[10:]