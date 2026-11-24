import pytest
from flask import g

from app import create_app
from app.extensions import db
from app.models import Reaction
from app.services import (
    artist_service,
    auth_service,
    comment_service,
    moderation_service,
    song_service,
)

PASSWORD = "correct-horse-battery"
ADMIN = "/api/v1/admin/moderation"


def make_user(number):
    return auth_service.register_user(f"fan{number}@example.com", f"fan_{number}", PASSWORD)


def make_admin(number):
    user = make_user(number)
    user.role = "admin"
    db.session.commit()
    return user


def make_song(title="Free Mind"):
    artist = artist_service.create_artist({"name": f"Artist for {title}"})
    return song_service.create_song(
        {"title": title, "artists": [{"artist_id": artist.id, "role": "primary"}]}
    )


def login_as(app, number):
    user = make_user(number)
    client = app.test_client()
    response = client.post(
        "/api/v1/auth/login", json={"identifier": f"fan_{number}", "password": PASSWORD}
    )
    assert response.status_code == 200
    return client, user


def test_writing_routes_require_login(app, client):
    song = make_song()
    calls = [
        ("put", f"/api/v1/songs/{song.id}/reactions/like"),
        ("delete", f"/api/v1/songs/{song.id}/reactions/like"),
        ("post", f"/api/v1/songs/{song.id}/comments"),
        ("patch", "/api/v1/comments/1"),
        ("delete", "/api/v1/comments/1"),
        ("post", "/api/v1/comments/1/report"),
    ]
    for method, url in calls:
        assert getattr(client, method)(url, json={}).status_code == 401, (method, url)


def test_song_community_stats(app, client):
    song = make_song()

    anonymous = client.get(f"/api/v1/songs/{song.id}/community")
    assert anonymous.status_code == 200
    assert anonymous.get_json()["data"] == {
        "likes": 0, "recommends": 0, "comments": 0, "commenters": 0,
    }
    assert anonymous.headers["Cache-Control"] == "private, no-store"

    fan, _ = login_as(app, 1)
    mine = fan.get(f"/api/v1/songs/{song.id}/community").get_json()["data"]
    assert mine["me"] == {"liked": False, "recommended": False}
    assert client.get("/api/v1/songs/999999/community").status_code == 404


def test_reacting_through_the_api(app):
    song = make_song()
    fan, _ = login_as(app, 1)
    url = f"/api/v1/songs/{song.id}/reactions"

    first = fan.put(f"{url}/like")
    assert first.status_code == 200
    assert first.get_json()["data"] == {"kind": "like", "active": True, "changed": True}
    assert fan.put(f"{url}/like").get_json()["data"]["changed"] is False
    assert fan.put(f"{url}/recommend").status_code == 200

    stats = fan.get(f"/api/v1/songs/{song.id}/community").get_json()["data"]
    assert (stats["likes"], stats["recommends"]) == (1, 1)
    assert stats["me"] == {"liked": True, "recommended": True}

    gone = fan.delete(f"{url}/like")
    assert gone.get_json()["data"] == {"kind": "like", "active": False, "changed": True}
    assert fan.put(f"{url}/love").status_code == 422
    assert fan.put("/api/v1/songs/999999/reactions/like").status_code == 404


def test_comment_lifecycle_through_the_api(app, client):
    song = make_song()
    fan, user = login_as(app, 1)
    other, _ = login_as(app, 2)
    base = f"/api/v1/songs/{song.id}/comments"

    created = fan.post(base, json={"body": "  Love this  "})
    assert created.status_code == 201
    comment = created.get_json()["data"]
    assert comment["body"] == "Love this"
    assert comment["author"] == {"id": user.id, "username": "fan_1"}
    assert comment["state"] == "visible"
    assert "email" not in str(comment)

    reply = other.post(base, json={"body": "Same here", "parent_id": comment["id"]})
    assert reply.status_code == 201

    listing = client.get(base).get_json()
    assert listing["meta"]["total"] == 1
    thread = listing["data"][0]
    assert thread["body"] == "Love this"
    assert [r["body"] for r in thread["replies"]] == ["Same here"]

    edited = fan.patch(f"/api/v1/comments/{comment['id']}", json={"body": "Love this a lot"})
    assert edited.get_json()["data"]["edited_at"]
    hijack = other.patch(f"/api/v1/comments/{comment['id']}", json={"body": "Hijack"})
    assert hijack.status_code == 403
    assert fan.post(base, json={"body": "Love this a lot"}).status_code == 409
    assert fan.post(base, json={}).status_code == 422

    assert fan.delete(f"/api/v1/comments/{comment['id']}").status_code == 200
    assert fan.delete(f"/api/v1/comments/{comment['id']}").status_code == 404
    after = client.get(base).get_json()["data"][0]
    assert after["state"] == "deleted" and after["body"] is None
    assert after["placeholder"] == "This comment was deleted."


def test_removed_comments_show_a_placeholder_to_the_public(app, client):
    song = make_song()
    fan, other, admin = make_user(1), make_user(2), make_admin(3)
    parent = comment_service.create_comment(fan, song.id, {"body": "Awful take"})
    comment_service.create_comment(other, song.id, {"body": "Disagree", "parent_id": parent.id})
    moderation_service.remove_comment(admin, parent.id, note="Abuse")

    data = client.get(f"/api/v1/songs/{song.id}/comments").get_json()["data"][0]

    assert data["state"] == "removed"
    assert data["body"] is None and data["author"] is None
    assert data["placeholder"] == "This comment was removed by a moderator."
    assert "Abuse" not in str(data)
    assert [r["body"] for r in data["replies"]] == ["Disagree"]


def test_reporting_through_the_api(app):
    song = make_song()
    author = make_user(1)
    comment = comment_service.create_comment(author, song.id, {"body": "Rude"})
    fan, _ = login_as(app, 2)
    url = f"/api/v1/comments/{comment.id}/report"

    assert fan.post(url, json={"reason": "abuse", "details": "Insults people"}).status_code == 201
    assert fan.post(url, json={"reason": "abuse"}).status_code == 409
    assert fan.post(url, json={}).status_code == 422
    assert fan.post(url, json={"reason": "boring"}).status_code == 422
    assert fan.post(url, json={"reason": "spam", "extra": 1}).status_code == 422
    assert fan.post("/api/v1/comments/999999/report", json={"reason": "spam"}).status_code == 404


def test_song_rankings_endpoint(app, client):
    song = make_song()
    for number in (1, 2, 3):
        user = make_user(number)
        db.session.add(Reaction(user_id=user.id, song_id=song.id, kind="recommend"))
    db.session.commit()

    response = client.get("/api/v1/rankings/songs")
    body = response.get_json()

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "public, max-age=300"
    assert body["meta"]["period"] == "trending" and body["meta"]["total"] == 1
    assert body["meta"]["source"] == "community"
    assert "streaming" in body["meta"]["note"]
    (item,) = body["data"]
    assert item["rank"] == 1 and item["song"]["id"] == song.id
    assert item["community"] == {
        "score": 9, "likes": 0, "recommends": 3, "commenters": 0, "engaged_users": 3,
    }
    all_time = client.get("/api/v1/rankings/songs?period=all_time")
    assert all_time.get_json()["meta"]["period"] == "all_time"


@pytest.mark.parametrize("query", ["?period=daily", "?limit=0", "?limit=51"])
def test_ranking_parameters_are_validated(client, query):
    assert client.get("/api/v1/rankings/songs" + query).status_code == 422


def test_recent_discussions_endpoint(app, client):
    song, fan = make_song(), make_user(1)
    comment_service.create_comment(fan, song.id, {"body": "Anyone else hooked?"})

    body = client.get("/api/v1/discussions/recent").get_json()

    assert body["meta"]["total"] == 1
    (item,) = body["data"]
    assert item["comment"]["body"] == "Anyone else hooked?"
    assert item["song"]["id"] == song.id and item["song"]["title"] == "Free Mind"


def test_the_community_rules_are_public(client):
    body = client.get("/api/v1/community/rules").get_json()["data"]
    assert body["version"]
    assert body["rules"]["recommend_points"] == 3
    assert body["rules"]["auto_hide_reports"] == 3


@pytest.fixture
def limited_app(tmp_path):
    app = create_app(
        "testing", {"RATELIMIT_ENABLED": True, "UPLOAD_DIR": str(tmp_path / "uploads")}
    )
    uri = app.config["SQLALCHEMY_DATABASE_URI"] or ""
    assert uri.endswith("_test"), "Refusing to run tests against a non-test database"

    @app.before_request
    def reset_login_cache():
        g.pop("_login_user", None)

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def test_commenting_is_rate_limited(limited_app):
    song = make_song()
    fan, _ = login_as(limited_app, 1)

    statuses = [
        fan.post(
            f"/api/v1/songs/{song.id}/comments", json={"body": f"Comment number {n}"}
        ).status_code
        for n in range(6)
    ]

    assert statuses == [201] * 5 + [429]


# ---------- moderation endpoints ----------

def test_moderation_routes_require_an_admin(app, client, user_client):
    calls = [
        ("get", f"{ADMIN}/queue"),
        ("post", f"{ADMIN}/comments/1/remove"),
        ("post", f"{ADMIN}/comments/1/restore"),
        ("post", f"{ADMIN}/comments/1/dismiss"),
        ("post", f"{ADMIN}/users/1/mute"),
        ("post", f"{ADMIN}/users/1/unmute"),
    ]
    for method, url in calls:
        assert getattr(client, method)(url, json={}).status_code == 401, (method, url)
        assert getattr(user_client, method)(url, json={}).status_code == 403, (method, url)


def test_the_moderation_queue_and_actions(app, admin_client):
    author, song = make_user(1), make_song()
    comment = comment_service.create_comment(author, song.id, {"body": "Rude words"})
    for number in (2, 3):
        moderation_service.report_comment(make_user(number), comment.id, "abuse")

    queue = admin_client.get(f"{ADMIN}/queue").get_json()
    assert queue["meta"]["total"] == 1
    item = queue["data"][0]
    assert item["comment"]["body"] == "Rude words" and item["report_count"] == 2
    assert [r["reason"] for r in item["reports"]] == ["abuse", "abuse"]
    assert item["author"]["username"] == "fan_1"

    removed = admin_client.post(f"{ADMIN}/comments/{comment.id}/remove", json={"note": "Insulting"})
    assert removed.status_code == 200
    assert removed.get_json()["data"]["state"] == "removed"
    assert admin_client.get(f"{ADMIN}/queue").get_json()["meta"]["total"] == 0
    assert admin_client.post(f"{ADMIN}/comments/{comment.id}/remove", json={}).status_code == 409

    restored = admin_client.post(f"{ADMIN}/comments/{comment.id}/restore")
    assert restored.get_json()["data"]["state"] == "visible"
    assert admin_client.post(f"{ADMIN}/comments/999999/dismiss").status_code == 404


def test_muting_through_the_api(app, admin_client):
    fan = make_user(1)
    url = f"{ADMIN}/users/{fan.id}"

    response = admin_client.post(f"{url}/mute", json={"days": 3})
    assert response.status_code == 200
    assert response.get_json()["data"]["muted_until"]

    assert admin_client.post(f"{url}/mute", json={"days": 0}).status_code == 422
    assert admin_client.post(f"{url}/mute", json={}).status_code == 422
    assert admin_client.post(f"{ADMIN}/users/999999/mute", json={"days": 3}).status_code == 404
    assert admin_client.post(f"{url}/unmute").get_json()["data"]["muted_until"] is None