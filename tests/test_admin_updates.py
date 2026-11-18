import pytest

from app.services import album_service, artist_service, song_service, update_service

URL = "/api/v1/admin/updates"
BODY = "Tems has announced a new single arriving this Friday on all platforms."


def new_artist(name="Tems"):
    return artist_service.create_artist({"name": name})


def new_update(artist=None, **extra):
    artist = artist or new_artist()
    data = {"artist_id": artist.id, "title": "New single announced", "body": BODY, **extra}
    return update_service.create_update(data)


def test_editorial_routes_require_an_admin(app, client, user_client):
    calls = [
        ("get", URL),
        ("post", URL),
        ("get", f"{URL}/1"),
        ("patch", f"{URL}/1"),
        ("post", f"{URL}/1/publish"),
        ("post", f"{URL}/1/unpublish"),
        ("post", f"{URL}/1/archive"),
        ("post", f"{URL}/1/restore"),
        ("get", "/api/v1/admin/editorial/summary"),
    ]
    for method, url in calls:
        assert getattr(client, method)(url, json={}).status_code == 401, (method, url)
        assert getattr(user_client, method)(url, json={}).status_code == 403, (method, url)


def test_create_draft_update(admin_client):
    tems = new_artist()

    response = admin_client.post(
        URL,
        json={
            "artist_id": tems.id,
            "title": "  New single announced ",
            "summary": "Out Friday.",
            "body": BODY,
            "category": "release",
            "source_name": "Tems Official",
            "source_url": "https://tems.example/news/1",
        },
    )
    data = response.get_json()["data"]

    assert response.status_code == 201
    assert data["title"] == "New single announced"
    assert data["status"] == "draft"
    assert data["published_at"] is None
    assert data["category"] == "release"
    assert data["author"] == "boss_user"
    assert data["artist"] == {"id": tems.id, "name": "Tems", "slug": "tems"}
    assert data["source"] == {"name": "Tems Official", "url": "https://tems.example/news/1"}
    assert data["song"] is None and data["album"] is None

    minimal = admin_client.post(URL, json={"artist_id": tems.id, "title": "Just an idea"})
    assert minimal.status_code == 201
    assert minimal.get_json()["data"]["category"] == "news"
    assert minimal.get_json()["data"]["body"] == ""


@pytest.mark.parametrize(
    "build, field",
    [
        (lambda a: {}, "artist_id"),
        (lambda a: {"artist_id": a}, "title"),
        (lambda a: {"artist_id": a, "title": "ab"}, "title"),
        (lambda a: {"artist_id": a, "title": "Valid title", "category": "gossip"}, "category"),
        (lambda a: {"artist_id": a, "title": "Valid title", "summary": "s" * 301}, "summary"),
        (lambda a: {"artist_id": a, "title": "Valid title", "body": "b" * 20001}, "body"),
        (
            lambda a: {"artist_id": a, "title": "Valid title", "source_url": "https://x.example/a"},
            "source_name",
        ),
        (
            lambda a: {
                "artist_id": a, "title": "Valid title",
                "source_name": "X", "source_url": "http://x.example/a",
            },
            "source_url",
        ),
        (lambda a: {"artist_id": 999999, "title": "Valid title"}, "artist_id"),
        (lambda a: {"artist_id": str(a), "title": "Valid title"}, "artist_id"),
        (lambda a: {"artist_id": a, "title": "Valid title", "status": "published"}, "status"),
        (lambda a: {"artist_id": a, "title": "Valid title", "author_id": 1}, "author_id"),
        (
            lambda a: {"artist_id": a, "title": "Valid title", "published_at": "2026-01-01T00:00:00Z"},
            "published_at",
        ),
    ],
)
def test_create_validation(admin_client, build, field):
    artist_id = new_artist().id
    response = admin_client.post(URL, json=build(artist_id))
    assert response.status_code == 422
    assert field in response.get_json()["error"]["details"]


def test_cannot_create_an_update_for_an_archived_artist(admin_client):
    tems = new_artist()
    artist_service.archive_artist(tems)

    response = admin_client.post(URL, json={"artist_id": tems.id, "title": "Late news"})

    assert response.status_code == 422
    assert "artist_id" in response.get_json()["error"]["details"]


def test_update_can_reference_a_song_and_album_of_its_artist(admin_client):
    tems = new_artist()
    song = song_service.create_song({"title": "Free Mind", "artists": [{"artist_id": tems.id}]})
    album = album_service.create_album({"artist_id": tems.id, "title": "Born in the Wild"})

    response = admin_client.post(
        URL,
        json={"artist_id": tems.id, "title": "Album news", "song_id": song.id, "album_id": album.id},
    )
    data = response.get_json()["data"]

    assert response.status_code == 201
    assert data["song"] == {"id": song.id, "title": "Free Mind"}
    assert data["album"] == {"id": album.id, "title": "Born in the Wild"}


def test_song_and_album_must_belong_to_the_artist(admin_client):
    tems, rema = new_artist("Tems"), new_artist("Rema")
    rema_song = song_service.create_song({"title": "Calm Down", "artists": [{"artist_id": rema.id}]})
    rema_album = album_service.create_album({"artist_id": rema.id, "title": "Rave & Roses"})
    own_song = song_service.create_song({"title": "Free Mind", "artists": [{"artist_id": tems.id}]})
    song_service.archive_song(own_song)
    base = {"artist_id": tems.id, "title": "Some news"}

    def field_errors(extra):
        response = admin_client.post(URL, json={**base, **extra})
        assert response.status_code == 422
        return response.get_json()["error"]["details"]

    assert "song_id" in field_errors({"song_id": rema_song.id})
    assert "song_id" in field_errors({"song_id": own_song.id})
    assert "song_id" in field_errors({"song_id": 999999})
    assert "album_id" in field_errors({"album_id": rema_album.id})
    assert "album_id" in field_errors({"album_id": 999999})


def test_update_changes_only_given_fields(admin_client):
    update = new_update(
        summary="Original summary", source_name="Blog", source_url="https://blog.example/a"
    )
    url = f"{URL}/{update.id}"

    data = admin_client.patch(
        url, json={"title": "Better title", "category": "interview"}
    ).get_json()["data"]

    assert data["title"] == "Better title"
    assert data["category"] == "interview"
    assert data["summary"] == "Original summary"
    assert data["source"] == {"name": "Blog", "url": "https://blog.example/a"}
    assert data["body"] == BODY
    assert data["status"] == "draft"

    cleared = admin_client.patch(
        url, json={"summary": "", "source_name": None, "source_url": None}
    ).get_json()["data"]
    assert cleared["summary"] is None
    assert cleared["source"] is None

    moved = admin_client.patch(url, json={"artist_id": 1})
    assert moved.status_code == 422
    assert "artist_id" in moved.get_json()["error"]["details"]
    assert admin_client.patch(url, json={}).status_code == 422
    assert admin_client.patch(url, json={"status": "published"}).status_code == 422


def test_update_rejects_bad_requests_without_changing_anything(admin_client):
    update = new_update()
    url = f"{URL}/{update.id}"

    response = admin_client.patch(url, json={"title": "Another title", "category": "gossip"})

    assert response.status_code == 422
    assert update_service.get_update(update.id, include_hidden=True).title == "New single announced"
    assert admin_client.patch(f"{URL}/999999", json={"title": "Another title"}).status_code == 404


def test_publish_unpublish_cycle(admin_client):
    update = new_update()
    url = f"{URL}/{update.id}"

    published = admin_client.post(f"{url}/publish").get_json()["data"]
    assert published["status"] == "published"
    first_time = published["published_at"]
    assert first_time is not None

    again = admin_client.post(f"{url}/publish").get_json()["data"]
    assert again["published_at"] == first_time

    draft = admin_client.post(f"{url}/unpublish").get_json()["data"]
    assert draft["status"] == "draft"
    assert draft["published_at"] is None
    assert admin_client.post(f"{url}/unpublish").status_code == 200

    republished = admin_client.post(f"{url}/publish").get_json()["data"]
    assert republished["status"] == "published"
    assert republished["published_at"] is not None


def test_cannot_publish_an_unfinished_update(admin_client):
    tems = new_artist()
    empty = update_service.create_update({"artist_id": tems.id, "title": "Placeholder idea"})

    response = admin_client.post(f"{URL}/{empty.id}/publish")
    assert response.status_code == 422
    assert "body" in response.get_json()["error"]["details"]
    assert update_service.get_update(empty.id, include_hidden=True).status == "draft"

    ready = new_update(tems)
    artist_service.archive_artist(tems)
    response = admin_client.post(f"{URL}/{ready.id}/publish")
    assert response.status_code == 422
    assert "artist_id" in response.get_json()["error"]["details"]


def test_published_update_must_stay_publishable_when_edited(admin_client):
    update = new_update()
    url = f"{URL}/{update.id}"
    admin_client.post(f"{url}/publish")

    response = admin_client.patch(url, json={"body": "Too short"})
    assert response.status_code == 422
    assert "body" in response.get_json()["error"]["details"]
    assert update_service.get_update(update.id, include_hidden=True).body == BODY

    response = admin_client.patch(url, json={"title": "A corrected title"})
    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == "published"


def test_archive_and_restore(admin_client):
    update = new_update()
    url = f"{URL}/{update.id}"
    admin_client.post(f"{url}/publish")

    archived = admin_client.post(f"{url}/archive").get_json()["data"]
    assert archived["status"] == "archived"
    assert admin_client.post(f"{url}/archive").status_code == 200
    assert admin_client.post(f"{url}/publish").status_code == 409
    assert admin_client.post(f"{url}/unpublish").status_code == 409
    assert admin_client.patch(url, json={"title": "Edited while archived"}).status_code == 409

    restored = admin_client.post(f"{url}/restore").get_json()["data"]
    assert restored["status"] == "draft"
    assert restored["published_at"] is None
    assert admin_client.post(f"{url}/restore").status_code == 200


def test_actions_on_unknown_updates_return_404(admin_client):
    for action in ["publish", "unpublish", "archive", "restore"]:
        assert admin_client.post(f"{URL}/999999/{action}").status_code == 404, action
    assert admin_client.get(f"{URL}/999999").status_code == 404


def test_admin_list_filters(admin_client):
    tems, rema = new_artist("Tems"), new_artist("Rema")
    new_update(tems, title="Draft about tour")
    live = new_update(tems, title="Single is out", category="release")
    gone = new_update(rema, title="Old story")
    update_service.publish_update(live)
    update_service.archive_update(gone)

    def titles(query):
        body = admin_client.get(f"{URL}?{query}").get_json()
        return sorted(u["title"] for u in body["data"])

    assert titles("") == ["Draft about tour", "Old story", "Single is out"]
    assert titles("status=draft") == ["Draft about tour"]
    assert titles("status=published") == ["Single is out"]
    assert titles("status=archived") == ["Old story"]
    assert titles(f"artist_id={rema.id}") == ["Old story"]
    assert titles("artist=tems") == ["Draft about tour", "Single is out"]
    assert titles("category=release") == ["Single is out"]
    assert titles("q=TOUR") == ["Draft about tour"]
    assert admin_client.get(f"{URL}?status=bogus").status_code == 422
    assert admin_client.get(f"{URL}?category=gossip").status_code == 422
    assert admin_client.get(f"{URL}?artist_id=abc").status_code == 422


def test_editorial_summary_counts(admin_client):
    tems = new_artist()
    new_update(tems)
    new_update(tems)
    update_service.publish_update(new_update(tems))
    update_service.archive_update(new_update(tems))

    body = admin_client.get("/api/v1/admin/editorial/summary").get_json()["data"]

    assert body == {"draft": 2, "published": 1, "archived": 1, "total": 4}