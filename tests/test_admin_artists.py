import pytest
import sqlalchemy as sa

from app.extensions import db
from app.models import Song, SongArtist
from app.services import artist_service, genre_service

URL = "/api/v1/admin/artists"


def test_admin_routes_require_an_admin(app, client, user_client):
    artist = artist_service.create_artist({"name": "Tems"})
    calls = [
        ("get", URL),
        ("post", URL),
        ("get", f"{URL}/{artist.id}"),
        ("patch", f"{URL}/{artist.id}"),
        ("post", f"{URL}/{artist.id}/archive"),
        ("post", f"{URL}/{artist.id}/restore"),
        ("post", f"{URL}/{artist.id}/image"),
        ("delete", f"{URL}/{artist.id}/image"),
    ]
    for method, url in calls:
        assert getattr(client, method)(url, json={}).status_code == 401, (method, url)
        assert getattr(user_client, method)(url, json={}).status_code == 403, (method, url)


def test_create_artist(admin_client):
    genre_service.create_genre("Afrobeats")

    response = admin_client.post(
        URL,
        json={
            "name": "  Ayra Starr ",
            "bio": "Singer.",
            "origin_city": "Lagos",
            "debut_year": 2021,
            "genres": ["Afrobeats"],
        },
    )
    data = response.get_json()["data"]

    assert response.status_code == 201
    assert data["name"] == "Ayra Starr"
    assert data["slug"] == "ayra-starr"
    assert data["genres"] == [{"name": "Afrobeats", "slug": "afrobeats"}]
    assert data["archived_at"] is None


@pytest.mark.parametrize(
    "payload, field",
    [
        ({}, "name"),
        ({"name": "   "}, "name"),
        ({"name": "X", "debut_year": 1800}, "debut_year"),
        ({"name": "X", "debut_year": "2020"}, "debut_year"),
        ({"name": "X", "debut_year": True}, "debut_year"),
        ({"name": "X", "bio": "b" * 5001}, "bio"),
        ({"name": "X", "genres": ["no-such-genre"]}, "genres"),
        ({"name": "X", "genres": "afrobeats"}, "genres"),
        ({"name": "X", "image_url": "http://evil.example/x.png"}, "image_url"),
        ({"name": "X", "role": "admin"}, "role"),
    ],
)
def test_create_validation(admin_client, payload, field):
    response = admin_client.post(URL, json=payload)
    assert response.status_code == 422
    assert field in response.get_json()["error"]["details"]


def test_duplicate_name_rejected_case_insensitively(admin_client):
    assert admin_client.post(URL, json={"name": "Tems"}).status_code == 201
    response = admin_client.post(URL, json={"name": "TEMS"})
    assert response.status_code == 409
    assert "name" in response.get_json()["error"]["details"]


def test_slug_collisions_get_a_numeric_suffix(admin_client):
    first = admin_client.post(URL, json={"name": "Ayra Starr"}).get_json()["data"]
    second = admin_client.post(URL, json={"name": "Ayra-Starr"}).get_json()["data"]
    assert (first["slug"], second["slug"]) == ("ayra-starr", "ayra-starr-2")


def test_update_changes_only_given_fields_and_keeps_slug(admin_client):
    genre_service.create_genre("Afrobeats")
    genre_service.create_genre("Amapiano")
    artist = artist_service.create_artist(
        {"name": "Tems", "bio": "Old bio", "genres": ["afrobeats"]}
    )

    response = admin_client.patch(
        f"{URL}/{artist.id}", json={"name": "TEMS", "genres": ["amapiano"]}
    )
    data = response.get_json()["data"]

    assert response.status_code == 200
    assert data["name"] == "TEMS"
    assert data["slug"] == "tems"
    assert data["bio"] == "Old bio"
    assert [g["slug"] for g in data["genres"]] == ["amapiano"]


def test_update_can_clear_optional_fields(admin_client):
    artist = artist_service.create_artist({"name": "Tems", "bio": "Bio", "debut_year": 2018})

    data = admin_client.patch(
        f"{URL}/{artist.id}", json={"bio": "", "debut_year": None}
    ).get_json()["data"]

    assert data["bio"] is None
    assert data["debut_year"] is None


def test_update_rejects_bad_requests_without_changing_anything(admin_client):
    tems = artist_service.create_artist({"name": "Tems"})
    artist_service.create_artist({"name": "Asake"})
    url = f"{URL}/{tems.id}"

    assert admin_client.patch(url, json={}).status_code == 422
    assert admin_client.patch(url, json={"name": "asake"}).status_code == 409
    assert admin_client.patch(f"{URL}/999999", json={"bio": "x"}).status_code == 404

    response = admin_client.patch(url, json={"name": "New Name", "debut_year": 1800})
    assert response.status_code == 422
    assert artist_service.get_artist_by_id(tems.id).name == "Tems"


def test_archive_hides_artist_but_keeps_its_data(admin_client, client):
    artist = artist_service.create_artist({"name": "Tems"})
    song = Song(title="Free Mind")
    song.credits = [SongArtist(artist=artist, role="primary")]
    db.session.add(song)
    db.session.commit()

    response = admin_client.post(f"{URL}/{artist.id}/archive")
    assert response.status_code == 200
    assert response.get_json()["data"]["archived_at"] is not None

    assert client.get("/api/v1/artists/tems").status_code == 404
    assert client.get("/api/v1/artists").get_json()["meta"]["total"] == 0
    archived = admin_client.get(f"{URL}?status=archived").get_json()
    assert [a["slug"] for a in archived["data"]] == ["tems"]
    assert admin_client.get(f"{URL}/{artist.id}").status_code == 200
    assert db.session.scalar(sa.select(sa.func.count()).select_from(SongArtist)) == 1

    restored = admin_client.post(f"{URL}/{artist.id}/restore")
    assert restored.get_json()["data"]["archived_at"] is None
    assert client.get("/api/v1/artists/tems").status_code == 200


def test_archive_and_restore_are_idempotent(admin_client):
    artist = artist_service.create_artist({"name": "Tems"})
    for action in ["archive", "archive", "restore", "restore"]:
        assert admin_client.post(f"{URL}/{artist.id}/{action}").status_code == 200


def test_admin_list_status_filter(admin_client):
    artist_service.create_artist({"name": "Tems"})
    gone = artist_service.create_artist({"name": "Asake"})
    artist_service.archive_artist(gone)

    def names(status):
        body = admin_client.get(f"{URL}?status={status}").get_json()
        return [a["name"] for a in body["data"]]

    assert names("active") == ["Tems"]
    assert names("archived") == ["Asake"]
    assert names("all") == ["Asake", "Tems"]
    assert admin_client.get(f"{URL}?status=bogus").status_code == 422