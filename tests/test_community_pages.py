import pytest

PASSWORD = "correct-horse-battery"


@pytest.mark.parametrize("path", ["/login", "/register", "/charts", "/discussions"])
def test_community_pages_render_the_html_shell(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.mimetype == "text/html"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert b'id="account"' in response.data
    assert b"/static/js/community.js" in response.data


def test_the_community_script_is_served(client):
    assert client.get("/static/js/community.js").status_code == 200


def test_the_session_endpoint_reports_who_is_signed_in(client):
    anonymous = client.get("/api/v1/auth/session")
    assert anonymous.status_code == 200
    assert anonymous.get_json() == {"data": None}
    assert anonymous.headers["Cache-Control"] == "no-store"

    client.post(
        "/api/v1/auth/register",
        json={"email": "ade@example.com", "username": "ade_music", "password": PASSWORD},
    )
    data = client.get("/api/v1/auth/session").get_json()["data"]
    assert data["username"] == "ade_music"
    assert "password_hash" not in data