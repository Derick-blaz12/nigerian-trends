import pytest

from app.services import album_service, artist_service, song_service, update_service

BODY = "A long enough announcement body for publishing."


def make_artist(name):
    return artist_service.create_artist({"name": name})


def make_update(artist, title, publish=True, **extra):
    update = update_service.create_update(
        {"artist_id": artist.id, "title": title, "body": BODY, **extra}
    )
    if publish:
        update = update_service.publish_update(update)
    return update


def test_only_published_updates_are_public(client):
    tems = make_artist("Tems")
    draft = make_update(tems, "Draft piece", publish=False)
    live = make_update(tems, "Live piece")
    archived = update_service.archive_update(make_update(tems, "Archived piece"))

    body = client.get("/api/v1/updates").get_json()

    assert [u["title"] for u in body["data"]] == ["Live piece"]
    assert body["meta"]["total"] == 1
    assert client.get(f"/api/v1/updates/{live.id}").status_code == 200
    assert client.get(f"/api/v1/updates/{draft.id}").status_code == 404
    assert client.get(f"/api/v1/updates/{archived.id}").status_code == 404
    assert client.get("/api/v1/updates/999999").status_code == 404


def test_newest_first_and_paginated(client):
    tems = make_artist("Tems")
    for title in ["First", "Second", "Third"]:
        make_update(tems, title)

    body = client.get("/api/v1/updates").get_json()
    assert [u["title"] for u in body["data"]] == ["Third", "Second", "First"]

    page = client.get("/api/v1/updates?per_page=2&page=2").get_json()
    assert [u["title"] for u in page["data"]] == ["First"]
    assert page["meta"] == {"page": 2, "per_page": 2, "total": 3}


def test_filters_by_artist_category_song_and_album(client):
    tems, rema = make_artist("Tems"), make_artist("Rema")
    song = song_service.create_song({"title": "Free Mind", "artists": [{"artist_id": tems.id}]})
    album = album_service.create_album({"artist_id": tems.id, "title": "Born in the Wild"})
    make_update(tems, "About the song", song_id=song.id, category="release")
    make_update(tems, "About the album", album_id=album.id)
    make_update(rema, "Rema interview", category="interview")

    def titles(query):
        body = client.get(f"/api/v1/updates?{query}").get_json()
        return sorted(u["title"] for u in body["data"])

    assert titles("artist=tems") == ["About the album", "About the song"]
    assert titles("category=interview") == ["Rema interview"]
    assert titles(f"song={song.id}") == ["About the song"]
    assert titles(f"album={album.id}") == ["About the album"]
    assert titles("artist=nobody") == []


def test_updates_disappear_when_unpublished_or_the_artist_is_archived(client):
    tems = make_artist("Tems")
    update = make_update(tems, "Big news")
    assert client.get("/api/v1/updates").get_json()["meta"]["total"] == 1

    artist_service.archive_artist(tems)
    assert client.get("/api/v1/updates").get_json()["meta"]["total"] == 0
    assert client.get(f"/api/v1/updates/{update.id}").status_code == 404

    artist_service.restore_artist(tems)
    assert client.get(f"/api/v1/updates/{update.id}").status_code == 200

    update_service.unpublish_update(update)
    assert client.get(f"/api/v1/updates/{update.id}").status_code == 404


def test_detail_shape_hides_admin_fields(client):
    tems = make_artist("Tems")
    song = song_service.create_song({"title": "Free Mind", "artists": [{"artist_id": tems.id}]})
    update = make_update(
        tems, "Big news", summary="Short version.", category="release",
        source_name="The Blog", source_url="https://blog.example/post", song_id=song.id,
    )

    data = client.get(f"/api/v1/updates/{update.id}").get_json()["data"]
    published_at = data.pop("published_at")

    assert published_at
    assert data == {
        "id": update.id,
        "title": "Big news",
        "summary": "Short version.",
        "category": "release",
        "body": BODY,
        "artist": {"id": tems.id, "name": "Tems", "slug": "tems"},
        "song": {"id": song.id, "title": "Free Mind"},
        "album": None,
        "source": {"name": "The Blog", "url": "https://blog.example/post"},
    }


def test_archived_song_is_not_shown_on_a_public_update(client, admin_client):
    tems = make_artist("Tems")
    song = song_service.create_song({"title": "Free Mind", "artists": [{"artist_id": tems.id}]})
    update = make_update(tems, "About the song", song_id=song.id)
    song_service.archive_song(song)

    public = client.get(f"/api/v1/updates/{update.id}").get_json()["data"]
    assert public["song"] is None

    admin = admin_client.get(f"/api/v1/admin/updates/{update.id}").get_json()["data"]
    assert admin["song"] == {"id": song.id, "title": "Free Mind"}


@pytest.mark.parametrize(
    "query", ["?category=gossip", "?song=abc", "?album=0", "?page=abc"]
)
def test_list_validation(client, query):
    response = client.get("/api/v1/updates" + query)
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "validation_error"