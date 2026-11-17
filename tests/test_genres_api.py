import pytest

from app.errors import ConflictError
from app.services import genre_service


def test_list_genres_when_empty(client):
    response = client.get("/api/v1/genres")
    body = response.get_json()
    assert response.status_code == 200
    assert body["data"] == []
    assert body["meta"]["total"] == 0


def test_list_genres_paginates(app, client):
    for name in ["Afrobeats", "Amapiano", "Highlife"]:
        genre_service.create_genre(name)

    body = client.get("/api/v1/genres?per_page=2").get_json()

    assert [g["slug"] for g in body["data"]] == ["afrobeats", "amapiano"]
    assert body["meta"]["total"] == 3


def test_get_genre_by_slug(app, client):
    genre_service.create_genre("Afro-fusion")
    response = client.get("/api/v1/genres/afro-fusion")
    assert response.status_code == 200
    assert response.get_json()["data"]["name"] == "Afro-fusion"


def test_unknown_genre_returns_404(client):
    response = client.get("/api/v1/genres/nope")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "not_found"


def test_invalid_pagination_returns_422(client):
    response = client.get("/api/v1/genres?page=abc")
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "validation_error"


def test_duplicate_genre_is_rejected(app):
    genre_service.create_genre("Afrobeats")
    with pytest.raises(ConflictError):
        genre_service.create_genre("afrobeats")