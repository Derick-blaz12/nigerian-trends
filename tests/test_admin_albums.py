import pytest

from app.services import album_service, artist_service

URL = "/api/v1/admin/albums"


def new_artist(name):
    return artist_service.create_artist({"name": name})


def test_create_album(admin_client):
    rema = new_artist("Rema")

    response = admin_client.post(
        URL,
        json={
            "artist_id": rema.id,
            "title": "  Rave & Roses ",
            "album_type": "album",
            "release_date": "2022-03-25",
        },
    )
    data = response.get_json()["data"]

    assert response.status_code == 201
    assert data["title"] == "Rave & Roses"
    assert data["album_type"] == "album"
    assert data["release_date"] == "2022-03-25"
    assert data["artist"] == {"id": rema.id, "name": "Rema", "slug": "rema"}
    assert data["tracks"] == []
    assert data["archived_at"] is None


@pytest.mark.parametrize(
    "build, field",
    [
        (lambda a: {}, "artist_id"),
        (lambda a: {"artist_id": a}, "title"),
        (lambda a: {"artist_id": a, "title": "X", "album_type": "boxset"}, "album_type"),
        (lambda a: {"artist_id": a, "title": "X", "release_date": "March"}, "release_date"),
        (lambda a: {"artist_id": 999999, "title": "X"}, "artist_id"),
        (lambda a: {"artist_id": str(a), "title": "X"}, "artist_id"),
        (lambda a: {"artist_id": a, "title": "X", "cover_url": "http://x.example/c.jpg"}, "cover_url"),
    ],
)
def test_create_album_validation(admin_client, build, field):
    artist_id = new_artist("Rema").id
    response = admin_client.post(URL, json=build(artist_id))
    assert response.status_code == 422
    assert field in response.get_json()["error"]["details"]


def test_duplicate_album_titles_for_one_artist_are_rejected(admin_client):
    rema, tems = new_artist("Rema"), new_artist("Tems")

    def post(artist, title):
        return admin_client.post(URL, json={"artist_id": artist.id, "title": title})

    assert post(rema, "Rave & Roses").status_code == 201
    duplicate = post(rema, "rave & roses")
    assert duplicate.status_code == 409
    assert "title" in duplicate.get_json()["error"]["details"]
    assert post(tems, "Rave & Roses").status_code == 201


def test_update_album_and_it_cannot_move_to_another_artist(admin_client):
    rema, tems = new_artist("Rema"), new_artist("Tems")
    album = album_service.create_album(
        {"artist_id": rema.id, "title": "Rave & Roses", "release_date": "2022-03-25"}
    )
    url = f"{URL}/{album.id}"

    data = admin_client.patch(
        url, json={"title": "Rave & Roses (Deluxe)", "album_type": "ep", "release_date": None}
    ).get_json()["data"]
    assert data["title"] == "Rave & Roses (Deluxe)"
    assert data["album_type"] == "ep"
    assert data["release_date"] is None

    moved = admin_client.patch(url, json={"artist_id": tems.id})
    assert moved.status_code == 422
    assert "artist_id" in moved.get_json()["error"]["details"]
    assert admin_client.patch(url, json={}).status_code == 422
    assert admin_client.patch(f"{URL}/999999", json={"title": "x"}).status_code == 404


def test_archive_and_restore_album(admin_client):
    album = album_service.create_album(
        {"artist_id": new_artist("Rema").id, "title": "Rave & Roses"}
    )
    url = f"{URL}/{album.id}"

    assert admin_client.post(f"{url}/archive").get_json()["data"]["archived_at"] is not None
    assert admin_client.post(f"{url}/archive").status_code == 200
    assert admin_client.post(f"{url}/restore").get_json()["data"]["archived_at"] is None
    assert admin_client.post(f"{url}/restore").status_code == 200
    assert admin_client.post(f"{URL}/999999/archive").status_code == 404


def test_admin_album_list_filters(admin_client):
    rema, tems = new_artist("Rema"), new_artist("Tems")
    album_service.create_album({"artist_id": rema.id, "title": "Rave & Roses"})
    album_service.create_album({"artist_id": tems.id, "title": "Born in the Wild"})
    old = album_service.create_album({"artist_id": tems.id, "title": "Old Tape"})
    album_service.archive_album(old)

    everything = admin_client.get(URL).get_json()
    assert sorted(a["title"] for a in everything["data"]) == ["Born in the Wild", "Rave & Roses"]

    by_artist = admin_client.get(f"{URL}?artist_id={rema.id}").get_json()
    assert [a["title"] for a in by_artist["data"]] == ["Rave & Roses"]

    archived = admin_client.get(f"{URL}?status=archived").get_json()
    assert [a["title"] for a in archived["data"]] == ["Old Tape"]

    assert admin_client.get(f"{URL}?q=wild").get_json()["meta"]["total"] == 1
    assert admin_client.get(f"{URL}?artist_id=abc").status_code == 422
    assert admin_client.get(f"{URL}?status=bogus").status_code == 422