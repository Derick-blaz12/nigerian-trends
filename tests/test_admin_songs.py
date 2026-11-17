import pytest

from app.services import album_service, artist_service, genre_service, song_service

URL = "/api/v1/admin/songs"


def new_artist(name):
    return artist_service.create_artist({"name": name})


def new_song(title, primary, **extra):
    return song_service.create_song(
        {"title": title, "artists": [{"artist_id": primary.id, "role": "primary"}], **extra}
    )


def test_catalogue_admin_routes_require_an_admin(app, client, user_client):
    calls = [
        ("get", "/api/v1/admin/songs"),
        ("post", "/api/v1/admin/songs"),
        ("get", "/api/v1/admin/songs/1"),
        ("patch", "/api/v1/admin/songs/1"),
        ("post", "/api/v1/admin/songs/1/archive"),
        ("post", "/api/v1/admin/songs/1/restore"),
        ("post", "/api/v1/admin/songs/1/links"),
        ("get", "/api/v1/admin/albums"),
        ("post", "/api/v1/admin/albums"),
        ("get", "/api/v1/admin/albums/1"),
        ("patch", "/api/v1/admin/albums/1"),
        ("post", "/api/v1/admin/albums/1/archive"),
        ("post", "/api/v1/admin/albums/1/restore"),
        ("post", "/api/v1/admin/albums/1/links"),
        ("post", "/api/v1/admin/artists/1/links"),
        ("delete", "/api/v1/admin/links/1"),
    ]
    for method, url in calls:
        assert getattr(client, method)(url, json={}).status_code == 401, (method, url)
        assert getattr(user_client, method)(url, json={}).status_code == 403, (method, url)


def test_create_song_with_collaborators(admin_client):
    genre_service.create_genre("Afrobeats")
    rema, selena = new_artist("Rema"), new_artist("Selena Gomez")

    response = admin_client.post(
        URL,
        json={
            "title": "  Calm Down ",
            "release_date": "2022-02-11",
            "duration_seconds": 239,
            "isrc": "nga0-12200001",
            "genres": ["afrobeats"],
            "artists": [
                {"artist_id": rema.id, "role": "primary"},
                {"artist_id": selena.id, "role": "featured"},
            ],
        },
    )
    data = response.get_json()["data"]

    assert response.status_code == 201
    assert data["title"] == "Calm Down"
    assert data["isrc"] == "NGA012200001"
    assert data["release_date"] == "2022-02-11"
    assert [(a["name"], a["role"]) for a in data["artists"]] == [
        ("Rema", "primary"),
        ("Selena Gomez", "featured"),
    ]
    assert data["genres"] == [{"name": "Afrobeats", "slug": "afrobeats"}]
    assert data["album"] is None
    assert data["archived_at"] is None


def test_one_artist_can_hold_several_roles(admin_client):
    tems = new_artist("Tems")
    response = admin_client.post(
        URL,
        json={
            "title": "Free Mind",
            "artists": [
                {"artist_id": tems.id, "role": "primary"},
                {"artist_id": tems.id, "role": "producer"},
            ],
        },
    )
    assert response.status_code == 201
    assert [a["role"] for a in response.get_json()["data"]["artists"]] == ["primary", "producer"]


@pytest.mark.parametrize(
    "build, field",
    [
        (lambda a: {}, "title"),
        (lambda a: {"title": "X"}, "artists"),
        (lambda a: {"title": "X", "artists": []}, "artists"),
        (lambda a: {"title": "X", "artists": [{"artist_id": a, "role": "featured"}]}, "artists"),
        (lambda a: {"title": "X", "artists": [{"artist_id": 999999}]}, "artists"),
        (lambda a: {"title": "X", "artists": [{"artist_id": a, "role": "dj"}]}, "artists"),
        (lambda a: {"title": "X", "artists": [{"artist_id": a}, {"artist_id": a}]}, "artists"),
        (lambda a: {"title": "X", "artists": [{"artist_id": a}], "release_date": "soon"}, "release_date"),
        (lambda a: {"title": "X", "artists": [{"artist_id": a}], "duration_seconds": 0}, "duration_seconds"),
        (lambda a: {"title": "X", "artists": [{"artist_id": a}], "isrc": "bad"}, "isrc"),
        (lambda a: {"title": "X", "artists": [{"artist_id": a}], "genres": ["nope"]}, "genres"),
        (lambda a: {"title": "X", "artists": [{"artist_id": a}], "plays": 5}, "plays"),
    ],
)
def test_create_song_validation(admin_client, build, field):
    artist_id = new_artist("Tems").id
    response = admin_client.post(URL, json=build(artist_id))
    assert response.status_code == 422
    assert field in response.get_json()["error"]["details"]


def test_duplicate_isrc_is_rejected(admin_client):
    rema, tems = new_artist("Rema"), new_artist("Tems")
    new_song("One", rema, isrc="NGA012200001")

    response = admin_client.post(
        URL, json={"title": "Two", "isrc": "NGA012200001", "artists": [{"artist_id": tems.id}]}
    )

    assert response.status_code == 409
    assert "isrc" in response.get_json()["error"]["details"]


def test_duplicate_titles_for_the_same_primary_artist_are_rejected(admin_client):
    rema, tems = new_artist("Rema"), new_artist("Tems")
    new_song("Calm Down", rema)

    def post(title, artist):
        return admin_client.post(URL, json={"title": title, "artists": [{"artist_id": artist.id}]})

    assert post("calm  DOWN!", rema).status_code == 409
    assert post("Calm Down (Remix)", rema).status_code == 201
    assert post("Calm Down", tems).status_code == 201


def test_duplicate_check_includes_archived_songs(admin_client):
    rema = new_artist("Rema")
    original = new_song("Calm Down", rema)
    song_service.archive_song(original)

    response = admin_client.post(
        URL, json={"title": "Calm Down", "artists": [{"artist_id": rema.id}]}
    )

    assert response.status_code == 409
    assert "archived" in response.get_json()["error"]["details"]["title"]


def test_album_artist_must_be_credited_on_the_song(admin_client):
    rema, tems = new_artist("Rema"), new_artist("Tems")
    album = album_service.create_album({"artist_id": rema.id, "title": "Rave & Roses"})

    wrong = admin_client.post(
        URL,
        json={"title": "Free Mind", "album_id": album.id, "artists": [{"artist_id": tems.id}]},
    )
    assert wrong.status_code == 422
    assert "album_id" in wrong.get_json()["error"]["details"]

    right = admin_client.post(
        URL,
        json={
            "title": "Free Mind",
            "album_id": album.id,
            "artists": [{"artist_id": tems.id}, {"artist_id": rema.id, "role": "featured"}],
        },
    )
    assert right.status_code == 201
    assert right.get_json()["data"]["album"] == {"id": album.id, "title": "Rave & Roses"}


def test_track_numbers_need_an_album_and_must_be_unique_within_it(admin_client):
    rema = new_artist("Rema")
    album = album_service.create_album({"artist_id": rema.id, "title": "Rave & Roses"})
    credits = [{"artist_id": rema.id}]

    loose = admin_client.post(URL, json={"title": "A", "track_number": 1, "artists": credits})
    assert loose.status_code == 422

    first = admin_client.post(
        URL, json={"title": "A", "album_id": album.id, "track_number": 1, "artists": credits}
    )
    assert first.status_code == 201
    clash = admin_client.post(
        URL, json={"title": "B", "album_id": album.id, "track_number": 1, "artists": credits}
    )
    assert clash.status_code == 409
    assert "track_number" in clash.get_json()["error"]["details"]
    fine = admin_client.post(
        URL, json={"title": "B", "album_id": album.id, "track_number": 2, "artists": credits}
    )
    assert fine.status_code == 201


def test_update_replaces_credits_and_genres(admin_client):
    genre_service.create_genre("Afrobeats")
    genre_service.create_genre("Amapiano")
    rema, tems = new_artist("Rema"), new_artist("Tems")
    song = new_song("Calm Down", rema, genres=["afrobeats"])
    url = f"{URL}/{song.id}"

    data = admin_client.patch(
        url,
        json={
            "artists": [{"artist_id": rema.id}, {"artist_id": tems.id, "role": "featured"}],
            "genres": ["amapiano"],
        },
    ).get_json()["data"]
    assert [(a["name"], a["role"]) for a in data["artists"]] == [
        ("Rema", "primary"),
        ("Tems", "featured"),
    ]
    assert [g["slug"] for g in data["genres"]] == ["amapiano"]

    data = admin_client.patch(url, json={"artists": [{"artist_id": tems.id}]}).get_json()["data"]
    assert [(a["name"], a["role"]) for a in data["artists"]] == [("Tems", "primary")]

    data = admin_client.patch(url, json={"title": "Calm Down (Remix)"}).get_json()["data"]
    assert data["title"] == "Calm Down (Remix)"
    assert [a["name"] for a in data["artists"]] == ["Tems"]


def test_update_rejects_bad_requests_without_changing_anything(admin_client):
    rema = new_artist("Rema")
    song = new_song("Calm Down", rema)
    new_song("Soso", rema)
    url = f"{URL}/{song.id}"

    assert admin_client.patch(url, json={}).status_code == 422
    assert admin_client.patch(f"{URL}/999999", json={"title": "x"}).status_code == 404
    assert admin_client.patch(url, json={"title": "soso"}).status_code == 409
    response = admin_client.patch(url, json={"title": "New Title", "duration_seconds": 0})
    assert response.status_code == 422
    assert song_service.get_song(song.id, include_hidden=True).title == "Calm Down"


def test_removing_the_album_clears_the_track_number(admin_client):
    rema = new_artist("Rema")
    album = album_service.create_album({"artist_id": rema.id, "title": "Rave & Roses"})
    song = new_song("Calm Down", rema, album_id=album.id, track_number=3)

    data = admin_client.patch(f"{URL}/{song.id}", json={"album_id": None}).get_json()["data"]

    assert data["album"] is None
    assert data["track_number"] is None


def test_archive_and_restore_song(admin_client):
    song = new_song("Calm Down", new_artist("Rema"))
    url = f"{URL}/{song.id}"

    assert admin_client.post(f"{url}/archive").get_json()["data"]["archived_at"] is not None
    assert admin_client.post(f"{url}/archive").status_code == 200
    assert admin_client.post(f"{url}/restore").get_json()["data"]["archived_at"] is None
    assert admin_client.post(f"{url}/restore").status_code == 200
    assert admin_client.post(f"{URL}/999999/archive").status_code == 404


def test_admin_song_list_filters_by_status(admin_client):
    rema = new_artist("Rema")
    new_song("Active One", rema)
    gone = new_song("Gone", rema)
    song_service.archive_song(gone)

    def titles(status):
        body = admin_client.get(f"{URL}?status={status}").get_json()
        return sorted(s["title"] for s in body["data"])

    assert titles("active") == ["Active One"]
    assert titles("archived") == ["Gone"]
    assert titles("all") == ["Active One", "Gone"]
    assert admin_client.get(f"{URL}?status=bogus").status_code == 422