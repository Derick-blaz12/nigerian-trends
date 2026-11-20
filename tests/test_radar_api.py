from datetime import timedelta

import pytest

from app.collectors import lastfm_sync
from app.models.mixins import utcnow
from app.services import album_service, artist_service, metric_service

ADMIN = "/api/v1/admin/radar"


def make_artist(name):
    return artist_service.create_artist({"name": name})


def add_album(artist, days_ago):
    return album_service.create_album(
        {
            "artist_id": artist.id,
            "title": "Debut EP",
            "album_type": "ep",
            "release_date": (utcnow().date() - timedelta(days=days_ago)).isoformat(),
        }
    )


def test_radar_endpoint_shape(client):
    tems = make_artist("Tems")
    add_album(tems, 20)

    response = client.get("/api/v1/radar")
    body = response.get_json()

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "public, max-age=300"
    assert body["meta"]["total"] == 1
    assert body["meta"]["limit"] == 12
    assert body["meta"]["rules_version"]
    assert "attribution" not in body["meta"]
    (item,) = body["data"]
    assert set(item) == {"rank", "artist", "score", "editors_pick", "reasons", "audience"}
    assert item["rank"] == 1 and item["score"] == 25 and item["editors_pick"] is False
    assert item["artist"]["slug"] == "tems"
    assert item["reasons"] == [{"label": "New release 20 days ago.", "points": 25}]
    assert item["audience"] is None


def test_radar_credits_the_audience_source(client):
    tems = make_artist("Tems")
    add_album(tems, 20)
    source = lastfm_sync.ensure_source()
    metric_service.record_snapshot(tems.id, source.id, "lastfm_listeners", 1200)

    body = client.get("/api/v1/radar").get_json()

    assert body["meta"]["attribution"] == "Audience figures from Last.fm."
    assert body["data"][0]["audience"] == {"listeners": 1200, "growth_pct": None, "span_days": 0}


@pytest.mark.parametrize("query", ["?limit=0", "?limit=51", "?limit=abc"])
def test_radar_limit_is_validated(client, query):
    response = client.get("/api/v1/radar" + query)
    assert response.status_code == 422


def test_the_rules_are_public(client):
    body = client.get("/api/v1/radar/rules").get_json()["data"]
    assert body["version"]
    assert body["rules"]["audience_ceiling"] == 300000
    assert body["rules"]["min_score_to_appear"] == 10
    assert body["commercial_mode"] is False


def test_radar_admin_routes_require_an_admin(app, client, user_client):
    calls = [
        ("get", f"{ADMIN}/explain/1"),
        ("get", f"{ADMIN}/entries"),
        ("put", f"{ADMIN}/entries/1"),
        ("delete", f"{ADMIN}/entries/1"),
    ]
    for method, url in calls:
        assert getattr(client, method)(url, json={}).status_code == 401, (method, url)
        assert getattr(user_client, method)(url, json={}).status_code == 403, (method, url)


def test_explain_shows_checks_components_and_inputs(admin_client):
    tems = make_artist("Tems")
    add_album(tems, 20)

    data = admin_client.get(f"{ADMIN}/explain/{tems.id}").get_json()["data"]

    assert data["appears"] is True and data["eligible"] is True and data["score"] == 25
    assert {c["name"] for c in data["checks"]} == {
        "has_content", "audience_size", "career_stage", "recent_activity",
    }
    assert data["components"] == [
        {"name": "new_release", "points": 25, "detail": "New release 20 days ago."}
    ]
    assert data["inputs"]["has_public_content"] is True
    assert data["inputs"]["last_release_date"] == (utcnow().date() - timedelta(days=20)).isoformat()
    assert data["artist"] == {"id": tems.id, "name": "Tems", "slug": "tems", "archived": False}


def test_explain_handles_unknown_and_archived_artists(admin_client):
    assert admin_client.get(f"{ADMIN}/explain/999999").status_code == 404

    tems = make_artist("Tems")
    add_album(tems, 20)
    artist_service.archive_artist(tems)

    data = admin_client.get(f"{ADMIN}/explain/{tems.id}").get_json()["data"]

    assert data["artist"]["archived"] is True
    assert data["appears"] is False
    assert any(c["name"] == "active_artist" and not c["passed"] for c in data["checks"])


def test_picking_listing_and_removing_an_entry(admin_client, client):
    tems = make_artist("Tems")
    url = f"{ADMIN}/entries/{tems.id}"

    response = admin_client.put(url, json={"status": "pick", "note": "One to watch"})
    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == "pick"

    listed = admin_client.get(f"{ADMIN}/entries").get_json()
    assert listed["meta"]["total"] == 1
    assert listed["data"][0]["artist"]["slug"] == "tems"
    assert admin_client.get(f"{ADMIN}/entries?status=excluded").get_json()["meta"]["total"] == 0

    public = client.get("/api/v1/radar").get_json()
    assert [item["reasons"][0]["label"] for item in public["data"]] == ["One to watch"]

    assert admin_client.delete(url).status_code == 200
    assert admin_client.delete(url).status_code == 404
    assert client.get("/api/v1/radar").get_json()["data"] == []
    assert admin_client.put(f"{ADMIN}/entries/999999", json={"status": "pick"}).status_code == 404


@pytest.mark.parametrize(
    "payload, field",
    [
        ({}, "status"),
        ({"status": "featured"}, "status"),
        ({"status": "pick", "note": "n" * 201}, "note"),
        ({"status": "excluded", "expires_on": "2099-01-01"}, "expires_on"),
        ({"status": "pick", "extra": 1}, "extra"),
    ],
)
def test_entry_validation(admin_client, payload, field):
    tems = make_artist("Tems")
    response = admin_client.put(f"{ADMIN}/entries/{tems.id}", json=payload)
    assert response.status_code == 422
    assert field in response.get_json()["error"]["details"]


def test_the_radar_page_renders(client):
    response = client.get("/radar")
    assert response.status_code == 200
    assert response.mimetype == "text/html"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]