from datetime import timedelta

import pytest

from app.models.mixins import utcnow
from app.services import (
    album_service,
    artist_service,
    auth_service,
    notification_service,
    song_service,
    update_service,
)

PASSWORD = "correct-horse-battery"
BODY = "A long enough announcement body for publishing."
ME = "/api/v1/me"


def make_user(number):
    return auth_service.register_user(f"fan{number}@example.com", f"fan_{number}", PASSWORD)


def login_as(app, number):
    user = make_user(number)
    client = app.test_client()
    response = client.post(
        "/api/v1/auth/login", json={"identifier": f"fan_{number}", "password": PASSWORD}
    )
    assert response.status_code == 200
    return client, user


def make_artist(name):
    return artist_service.create_artist({"name": name})


def days_ago(n):
    return (utcnow().date() - timedelta(days=n)).isoformat()


def make_song(title, artist, days=1):
    return song_service.create_song(
        {
            "title": title,
            "release_date": days_ago(days),
            "artists": [{"artist_id": artist.id, "role": "primary"}],
        }
    )


def add_album(artist, days=2, title="Debut EP"):
    return album_service.create_album(
        {"artist_id": artist.id, "title": title, "album_type": "ep", "release_date": days_ago(days)}
    )


def publish_news(artist, title="Big news"):
    update = update_service.create_update({"artist_id": artist.id, "title": title, "body": BODY})
    return update_service.publish_update(update)


def test_personal_routes_require_login(app, client):
    make_artist("Tems")
    calls = [
        ("put", "/api/v1/artists/tems/follow"),
        ("delete", "/api/v1/artists/tems/follow"),
        ("get", f"{ME}/following"),
        ("get", f"{ME}/feed"),
        ("get", f"{ME}/notifications"),
        ("get", f"{ME}/notifications/unread-count"),
        ("post", f"{ME}/notifications/1/read"),
        ("post", f"{ME}/notifications/read-all"),
        ("get", f"{ME}/notification-preferences"),
        ("patch", f"{ME}/notification-preferences"),
        ("get", f"{ME}/digest-preview"),
    ]
    for method, url in calls:
        assert getattr(client, method)(url, json={}).status_code == 401, (method, url)


def test_the_follower_count_is_public_and_your_choice_is_private(app, client):
    make_artist("Tems")

    anonymous = client.get("/api/v1/artists/tems/follow")
    assert anonymous.status_code == 200
    assert anonymous.get_json()["data"] == {"followers": 0}
    assert anonymous.headers["Cache-Control"] == "private, no-store"

    fan, _ = login_as(app, 1)
    assert fan.get("/api/v1/artists/tems/follow").get_json()["data"] == {
        "followers": 0,
        "me": {"following": False, "notify": False},
    }
    assert client.get("/api/v1/artists/nobody/follow").status_code == 404


def test_following_and_unfollowing_through_the_api(app, client):
    make_artist("Tems")
    gone = make_artist("Gone Act")
    fan, _ = login_as(app, 1)
    url = "/api/v1/artists/tems/follow"

    first = fan.put(url)
    assert first.status_code == 200
    assert first.get_json()["data"] == {"following": True, "notify": True, "changed": True}
    assert fan.put(url).get_json()["data"]["changed"] is False
    assert fan.get(url).get_json()["data"] == {
        "followers": 1,
        "me": {"following": True, "notify": True},
    }
    assert client.get(url).get_json()["data"] == {"followers": 1}

    assert fan.delete(url).get_json()["data"] == {
        "following": False, "notify": False, "changed": True,
    }
    assert fan.delete(url).get_json()["data"]["changed"] is False
    assert fan.get(url).get_json()["data"]["followers"] == 0

    assert fan.put("/api/v1/artists/nobody/follow").status_code == 404
    artist_service.archive_artist(gone)
    assert fan.put("/api/v1/artists/gone-act/follow").status_code == 404


def test_the_notification_choice_when_following(app):
    make_artist("Tems")
    fan, _ = login_as(app, 1)
    url = "/api/v1/artists/tems/follow"

    quiet = fan.put(url, json={"notify": False})
    assert quiet.get_json()["data"] == {"following": True, "notify": False, "changed": True}
    assert fan.get(url).get_json()["data"]["me"] == {"following": True, "notify": False}

    loud = fan.put(url, json={"notify": True})
    assert loud.get_json()["data"] == {"following": True, "notify": True, "changed": True}
    assert fan.put(url, json={}).get_json()["data"]["changed"] is False

    assert fan.put(url, json={"notify": "yes"}).status_code == 422
    assert fan.put(url, json={"alerts": True}).status_code == 422
    assert fan.put(url, json=[True]).status_code == 422


def test_the_following_list(app):
    make_artist("Asake")
    burna = make_artist("Burna Boy")
    make_artist("Cuppy")
    fan, _ = login_as(app, 1)
    for slug in ("asake", "burna-boy", "cuppy"):
        fan.put(f"/api/v1/artists/{slug}/follow")
    fan.put("/api/v1/artists/asake/follow", json={"notify": False})
    artist_service.archive_artist(burna)

    body = fan.get(f"{ME}/following").get_json()

    assert body["meta"] == {"page": 1, "per_page": 20, "total": 2}
    assert [a["slug"] for a in body["data"]] == ["cuppy", "asake"]
    assert body["data"][0]["notify"] is True and body["data"][1]["notify"] is False
    assert body["data"][0]["followed_at"]
    assert body["data"][0]["genres"] == []

    page2 = fan.get(f"{ME}/following?per_page=1&page=2").get_json()
    assert [a["slug"] for a in page2["data"]] == ["asake"]


def test_the_feed_endpoint(app):
    tems = make_artist("Tems")
    fan, _ = login_as(app, 1)
    fan.put("/api/v1/artists/tems/follow")
    song = make_song("Free Mind", tems, days=10)
    album = add_album(tems, days=5)
    update = publish_news(tems, "Big news")

    body = fan.get(f"{ME}/feed").get_json()

    assert body["meta"] == {"page": 1, "per_page": 20, "total": 3}
    assert [(i["kind"], i["item"]["title"]) for i in body["data"]] == [
        ("news", "Big news"),
        ("album", "Debut EP"),
        ("song", "Free Mind"),
    ]
    first = body["data"][0]
    assert set(first) == {"kind", "at", "artist", "item"}
    assert first["artist"] == {"id": tems.id, "name": "Tems", "slug": "tems", "image_url": None}
    assert first["item"]["id"] == update.id
    assert body["data"][1]["item"]["id"] == album.id
    assert body["data"][2]["item"]["id"] == song.id


@pytest.mark.parametrize("query", ["?page=abc", "?per_page=0", "?per_page=101"])
def test_paging_parameters_are_validated(app, query):
    fan, _ = login_as(app, 1)
    assert fan.get(f"{ME}/feed{query}").status_code == 422


def test_the_notifications_endpoints(app):
    tems = make_artist("Tems")
    fan, _ = login_as(app, 1)
    fan.put("/api/v1/artists/tems/follow")
    song = make_song("Free Mind", tems, days=2)
    notification_service.generate_notifications()

    body = fan.get(f"{ME}/notifications").get_json()

    assert body["meta"] == {"page": 1, "per_page": 20, "total": 1, "unread": 1}
    (item,) = body["data"]
    assert item["kind"] == "song" and item["read"] is False
    assert item["artist"]["slug"] == "tems"
    assert item["item"]["id"] == song.id and item["item"]["title"] == "Free Mind"
    assert item["created_at"]
    assert fan.get(f"{ME}/notifications/unread-count").get_json()["data"] == {"count": 1}


def test_marking_notifications_read(app):
    tems = make_artist("Tems")
    fan, _ = login_as(app, 1)
    other, _ = login_as(app, 2)
    fan.put("/api/v1/artists/tems/follow")
    other.put("/api/v1/artists/tems/follow")
    make_song("One", tems)
    make_song("Two", tems)
    notification_service.generate_notifications()

    items = fan.get(f"{ME}/notifications").get_json()["data"]
    assert len(items) == 2
    first_id = items[0]["id"]

    read = fan.post(f"{ME}/notifications/{first_id}/read")
    assert read.get_json()["data"] == {"id": first_id, "read": True}
    unread = fan.get(f"{ME}/notifications?unread=true").get_json()
    assert unread["meta"]["total"] == 1 and unread["meta"]["unread"] == 1
    assert fan.get(f"{ME}/notifications?unread=maybe").status_code == 422

    assert other.post(f"{ME}/notifications/{first_id}/read").status_code == 404
    assert fan.post(f"{ME}/notifications/999999/read").status_code == 404

    assert fan.post(f"{ME}/notifications/read-all").get_json()["data"] == {"marked": 1}
    assert fan.post(f"{ME}/notifications/read-all").get_json()["data"] == {"marked": 0}
    assert other.get(f"{ME}/notifications/unread-count").get_json()["data"] == {"count": 2}


def test_notification_preferences_endpoints(app):
    fan, _ = login_as(app, 1)
    url = f"{ME}/notification-preferences"

    assert fan.get(url).get_json()["data"] == {
        "notify_releases": True, "notify_news": True, "email_digest": False,
    }
    updated = fan.patch(url, json={"email_digest": True, "notify_news": False})
    assert updated.status_code == 200
    assert updated.get_json()["data"] == {
        "notify_releases": True, "notify_news": False, "email_digest": True,
    }
    assert fan.get(url).get_json()["data"]["notify_news"] is False

    assert fan.patch(url, json={}).status_code == 422
    assert fan.patch(url, json={"notify_news": "no"}).status_code == 422
    assert fan.patch(url, json={"colour": True}).status_code == 422


def test_the_digest_preview_endpoint(app):
    tems = make_artist("Tems")
    fan, _ = login_as(app, 1)
    url = f"{ME}/digest-preview"

    empty = fan.get(url).get_json()
    assert empty["data"] == {"email_digest_enabled": False, "preview": None}
    assert "not sent" in empty["meta"]["note"]

    fan.put("/api/v1/artists/tems/follow")
    make_song("Free Mind", tems)
    notification_service.generate_notifications()
    fan.patch(f"{ME}/notification-preferences", json={"email_digest": True})

    data = fan.get(url).get_json()["data"]
    assert data["email_digest_enabled"] is True
    assert data["preview"]["subject"] == "1 new thing from artists you follow"
    assert 'Tems: new song "Free Mind"' in data["preview"]["body"]


def test_personal_responses_are_never_cached(app):
    fan, _ = login_as(app, 1)
    for path in ("feed", "following", "notifications", "notification-preferences"):
        response = fan.get(f"{ME}/{path}")
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"


def test_the_follow_rules_are_public(client):
    body = client.get("/api/v1/follow/rules").get_json()["data"]
    assert body["version"]
    assert body["rules"]["max_follows"] == 500