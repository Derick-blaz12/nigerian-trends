import pytest

from app.services import album_service, artist_service, song_service

ADMIN = "/api/v1/admin"


def setup_catalogue():
    tems = artist_service.create_artist({"name": "Tems"})
    song = song_service.create_song({"title": "Free Mind", "artists": [{"artist_id": tems.id}]})
    album = album_service.create_album({"artist_id": tems.id, "title": "Born in the Wild"})
    return tems, song, album


def test_add_show_and_delete_links(admin_client, client):
    tems, song, album = setup_catalogue()

    created = admin_client.post(
        f"{ADMIN}/songs/{song.id}/links",
        json={"platform": "Spotify", "url": "https://open.spotify.com/track/abc"},
    )
    assert created.status_code == 201
    link = created.get_json()["data"]
    assert link["platform"] == "spotify"

    artist_link = admin_client.post(
        f"{ADMIN}/artists/{tems.id}/links",
        json={"platform": "website", "url": "https://tems.example/"},
    )
    assert artist_link.status_code == 201
    album_link = admin_client.post(
        f"{ADMIN}/albums/{album.id}/links",
        json={"platform": "apple_music", "url": "https://music.apple.com/ng/album/born-in-the-wild/1"},
    )
    assert album_link.status_code == 201

    assert client.get(f"/api/v1/songs/{song.id}").get_json()["data"]["links"] == [link]
    artist = client.get("/api/v1/artists/tems").get_json()["data"]
    assert [item["platform"] for item in artist["links"]] == ["website"]
    album_page = client.get(f"/api/v1/albums/{album.id}").get_json()["data"]
    assert [item["platform"] for item in album_page["links"]] == ["apple_music"]

    assert admin_client.delete(f"{ADMIN}/links/{link['id']}").status_code == 200
    assert client.get(f"/api/v1/songs/{song.id}").get_json()["data"]["links"] == []
    assert admin_client.delete(f"{ADMIN}/links/{link['id']}").status_code == 404


@pytest.mark.parametrize(
    "payload, field",
    [
        ({"platform": "spotify", "url": "https://evil.example/x"}, "url"),
        ({"platform": "tiktok", "url": "https://tiktok.com/x"}, "platform"),
        ({"platform": "spotify"}, "url"),
        ({"url": "https://open.spotify.com/x"}, "platform"),
        ({"platform": "spotify", "url": "https://open.spotify.com/x", "extra": 1}, "extra"),
    ],
)
def test_link_validation(admin_client, payload, field):
    _, song, _ = setup_catalogue()
    response = admin_client.post(f"{ADMIN}/songs/{song.id}/links", json=payload)
    assert response.status_code == 422
    assert field in response.get_json()["error"]["details"]


def test_a_link_cannot_be_reused_and_unknown_targets_return_404(admin_client):
    tems = artist_service.create_artist({"name": "Tems"})
    one = song_service.create_song({"title": "One", "artists": [{"artist_id": tems.id}]})
    two = song_service.create_song({"title": "Two", "artists": [{"artist_id": tems.id}]})
    payload = {"platform": "spotify", "url": "https://open.spotify.com/track/abc"}

    assert admin_client.post(f"{ADMIN}/songs/{one.id}/links", json=payload).status_code == 201
    assert admin_client.post(f"{ADMIN}/songs/{two.id}/links", json=payload).status_code == 409
    for kind in ["artists", "songs", "albums"]:
        assert admin_client.post(f"{ADMIN}/{kind}/999999/links", json=payload).status_code == 404


def test_links_per_item_are_limited(admin_client):
    _, song, _ = setup_catalogue()
    url = f"{ADMIN}/songs/{song.id}/links"

    for number in range(20):
        response = admin_client.post(
            url, json={"platform": "spotify", "url": f"https://open.spotify.com/track/{number}"}
        )
        assert response.status_code == 201

    response = admin_client.post(
        url, json={"platform": "spotify", "url": "https://open.spotify.com/track/over"}
    )
    assert response.status_code == 422