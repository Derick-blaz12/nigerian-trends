def test_unknown_route_returns_json_404(client):
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "not_found"


def test_unexpected_error_returns_safe_json_500(app, client):
    @app.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail")

    response = client.get("/boom")

    assert response.status_code == 500
    assert response.get_json()["error"]["code"] == "internal_error"
    assert "secret internal detail" not in response.get_data(as_text=True)


def test_every_response_has_a_request_id(client):
    response = client.get("/health")
    assert response.headers["X-Request-ID"]


def test_database_health_check(client):
    response = client.get("/health/db")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "database": "up"}