import pytest

from app.services import album_service, artist_service, genre_service, song_service


def make_artist(name):
    return artist_service.create_artist({"name": name})


def make_song(title, primary, *featured, **extra):
    credits = [{"artist_id": primary.id, "role": "primary"}]
    credits += [{"artist_id": a.id, "role": "featured"} for a in featured]
    return song_service.create_song({"title": title, "artists": credits, **extra})


def test_song_list_is_newest_first_and_paginated(client):
    rema = make_artist("Rema")
    make_song("Old", rema, release_date="2020-01-01")
    make_song("New", rema, release_date="2023-01-01")
    make_song("Undated", rema)

    body = client.get("/api/v1/songs").get_json()
    assert [s["title"] for s in body["data"]] == ["New", "Old", "Undated"]

    page = client.get("/api/v1/songs?per_page=2&page=2").get_json()
    assert [s["title"] for s in page["data"]] == ["Undated"]
    assert page["meta"] == {"page": 2, "per_page": 2, "total": 3}


def test_song_search_ranks_title_prefix_first_then_title_then_artist(client):
    rema, tems = make_artist("Rema"), make_artist("Tems")
    make_song("Calm Down", rema)
    make_song("Ode to Rema", tems)
    make_song("Rema Freestyle", tems)
    make_song("Soundgasm", tems)

    body = client.get("/api/v1/songs?q=REMA").get_json()

    assert [s["title"] for s in body["data"]] == ["Rema Freestyle", "Ode to Rema", "Calm Down"]
    assert body["meta"]["total"] == 3


def test_song_search_treats_wildcards_literally(client):
    make_song("Calm Down", make_artist("Rema"))
    assert client.get("/api/v1/songs?q=%25").get_json()["data"] == []
    assert client.get("/api/v1/songs?q=_").get_json()["data"] == []


def test_song_filters_by_genre_and_artist(client):
    genre_service.create_genre("Afrobeats")
    genre_service.create_genre("Highlife")
    rema, tems = make_artist("Rema"), make_artist("Tems")
    make_song("Calm Down", rema, genres=["afrobeats"])
    make_song("Free Mind", tems, rema, genres=["highlife"])

    def titles(query):
        return sorted(s["title"] for s in client.get(f"/api/v1/songs?{query}").get_json()["data"])

    assert titles("genre=highlife") == ["Free Mind"]
    assert titles("artist=rema") == ["Calm Down", "Free Mind"]
    assert titles("artist=tems") == ["Free Mind"]
    assert titles("artist=nobody") == []


def test_song_detail_shape(client):
    genre_service.create_genre("Afrobeats")
    rema, selena = make_artist("Rema"), make_artist("Selena Gomez")
    album = album_service.create_album({"artist_id": rema.id, "title": "Rave & Roses"})
    song = make_song(
        "Calm Down", rema, selena,
        release_date="2022-02-11", duration_seconds=239, isrc="NGA012200001",
        album_id=album.id, track_number=2, genres=["afrobeats"],
    )

    data = client.get(f"/api/v1/songs/{song.id}").get_json()["data"]

    assert data == {
        "id": song.id,
        "title": "Calm Down",
        "release_date": "2022-02-11",
        "duration_seconds": 239,
        "track_number": 2,
        "isrc": "NGA012200001",
        "album": {"id": album.id, "title": "Rave & Roses"},
        "genres": [{"name": "Afrobeats", "slug": "afrobeats"}],
        "artists": [
            {"id": rema.id, "name": "Rema", "slug": "rema", "role": "primary"},
            {"id": selena.id, "name": "Selena Gomez", "slug": "selena-gomez", "role": "featured"},
        ],
        "links": [],
    }


def test_archived_song_is_hidden_until_restored(client):
    rema = make_artist("Rema")
    song = make_song("Calm Down", rema)
    song_service.archive_song(song)

    assert client.get(f"/api/v1/songs/{song.id}").status_code == 404
    assert client.get("/api/v1/songs").get_json()["meta"]["total"] == 0
    assert client.get("/api/v1/artists/rema").get_json()["data"]["songs"] == []

    song_service.restore_song(song)
    assert client.get(f"/api/v1/songs/{song.id}").status_code == 200
    assert len(client.get("/api/v1/artists/rema").get_json()["data"]["songs"]) == 1


def test_songs_of_an_archived_primary_artist_are_hidden(client):
    rema, tems = make_artist("Rema"), make_artist("Tems")
    song = make_song("Calm Down", rema)
    make_song("Free Mind", tems)
    artist_service.archive_artist(rema)

    assert client.get(f"/api/v1/songs/{song.id}").status_code == 404
    listed = client.get("/api/v1/songs").get_json()["data"]
    assert [s["title"] for s in listed] == ["Free Mind"]
    assert client.get("/api/v1/search?q=calm").get_json()["meta"]["totals"]["songs"] == 0


def test_archived_featured_artist_is_not_credited_publicly(client, admin_client):
    rema, tems = make_artist("Rema"), make_artist("Tems")
    song = make_song("Calm Down", rema, tems)
    artist_service.archive_artist(tems)

    public = client.get(f"/api/v1/songs/{song.id}").get_json()["data"]
    assert [a["name"] for a in public["artists"]] == ["Rema"]

    admin = admin_client.get(f"/api/v1/admin/songs/{song.id}").get_json()["data"]
    assert [a["name"] for a in admin["artists"]] == ["Rema", "Tems"]


def test_album_detail_lists_public_tracks_in_order(client):
    rema = make_artist("Rema")
    album = album_service.create_album(
        {"artist_id": rema.id, "title": "Rave & Roses", "release_date": "2022-03-25"}
    )
    make_song("Second", rema, album_id=album.id, track_number=2)
    make_song("First", rema, album_id=album.id, track_number=1)
    make_song("Bonus", rema, album_id=album.id)
    hidden = make_song("Hidden", rema, album_id=album.id, track_number=3)
    song_service.archive_song(hidden)

    data = client.get(f"/api/v1/albums/{album.id}").get_json()["data"]

    assert data["title"] == "Rave & Roses"
    assert data["artist"] == {"id": rema.id, "name": "Rema", "slug": "rema"}
    assert [(t["track_number"], t["title"]) for t in data["tracks"]] == [
        (1, "First"),
        (2, "Second"),
        (None, "Bonus"),
    ]
    assert data["tracks"][0]["artists"] == [
        {"id": rema.id, "name": "Rema", "slug": "rema", "role": "primary"}
    ]


def test_archived_album_is_hidden_everywhere(client):
    rema = make_artist("Rema")
    album = album_service.create_album({"artist_id": rema.id, "title": "Rave & Roses"})
    album_service.archive_album(album)

    assert client.get(f"/api/v1/albums/{album.id}").status_code == 404
    assert client.get("/api/v1/artists/rema").get_json()["data"]["albums"] == []
    assert client.get("/api/v1/search?q=rave").get_json()["meta"]["totals"]["albums"] == 0

    album_service.restore_album(album)
    assert client.get(f"/api/v1/albums/{album.id}").status_code == 200
    assert client.get("/api/v1/search?q=rave").get_json()["meta"]["totals"]["albums"] == 1


def test_search_returns_grouped_results(client):
    rema, tems = make_artist("Rema"), make_artist("Tems")
    make_song("Calm Down", rema)
    make_song("Free Mind", tems)
    album_service.create_album({"artist_id": rema.id, "title": "Rave & Roses"})

    body = client.get("/api/v1/search?q=rema").get_json()

    assert [a["name"] for a in body["data"]["artists"]] == ["Rema"]
    assert [s["title"] for s in body["data"]["songs"]] == ["Calm Down"]
    assert [a["title"] for a in body["data"]["albums"]] == ["Rave & Roses"]
    assert body["meta"]["totals"] == {"artists": 1, "songs": 1, "albums": 1}
    assert body["meta"]["query"] == "rema"

    for title in ["Night One", "Night Two", "Night Three"]:
        make_song(title, tems)
    limited = client.get("/api/v1/search?q=night&limit=2").get_json()
    assert len(limited["data"]["songs"]) == 2
    assert limited["meta"]["totals"]["songs"] == 3


@pytest.mark.parametrize(
    "query",
    ["", "?q=a", "?q=" + "x" * 101, "?q=rema&limit=0", "?q=rema&limit=21", "?q=rema&limit=abc"],
)
def test_search_validation(client, query):
    response = client.get("/api/v1/search" + query)
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "validation_error"