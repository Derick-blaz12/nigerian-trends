from datetime import date

from app.extensions import db
from app.models import Song, SongArtist
from app.services import artist_service, genre_service


def make_artist(name, **extra):
    return artist_service.create_artist({"name": name, **extra})


def test_list_is_empty_at_first(client):
    body = client.get("/api/v1/artists").get_json()
    assert body["data"] == []
    assert body["meta"]["total"] == 0


def test_list_is_sorted_by_name_and_hides_archived(app, client):
    make_artist("Tems")
    hidden = make_artist("Burna Boy")
    make_artist("Asake")
    artist_service.archive_artist(hidden)

    body = client.get("/api/v1/artists").get_json()

    assert [a["name"] for a in body["data"]] == ["Asake", "Tems"]
    assert body["meta"]["total"] == 2


def test_search_is_case_insensitive_and_ranks_prefix_matches_first(app, client):
    make_artist("Ayra Starr")
    make_artist("Starboy Collective")
    make_artist("Burna Boy")

    body = client.get("/api/v1/artists?q=STAR").get_json()

    assert [a["name"] for a in body["data"]] == ["Starboy Collective", "Ayra Starr"]
    assert body["meta"]["total"] == 2


def test_search_treats_wildcards_literally(app, client):
    make_artist("Tems")
    make_artist("Asake")
    assert client.get("/api/v1/artists?q=%25").get_json()["data"] == []
    assert client.get("/api/v1/artists?q=_").get_json()["data"] == []


def test_search_query_length_is_limited(client):
    response = client.get("/api/v1/artists?q=" + "a" * 101)
    assert response.status_code == 422


def test_filter_by_genre(app, client):
    genre_service.create_genre("Afrobeats")
    genre_service.create_genre("Highlife")
    make_artist("Tems", genres=["afrobeats"])
    make_artist("Osadebe", genres=["highlife"])

    body = client.get("/api/v1/artists?genre=highlife").get_json()

    assert [a["slug"] for a in body["data"]] == ["osadebe"]
    assert body["data"][0]["genres"] == [{"name": "Highlife", "slug": "highlife"}]


def test_pagination(app, client):
    for name in ["A One", "B Two", "C Three"]:
        make_artist(name)

    body = client.get("/api/v1/artists?per_page=2&page=2").get_json()

    assert [a["name"] for a in body["data"]] == ["C Three"]
    assert body["meta"] == {"page": 2, "per_page": 2, "total": 3}


def test_detail_includes_profile_and_songs(app, client):
    genre_service.create_genre("Afrobeats")
    tems = make_artist(
        "Tems", bio="Singer", origin_city="Lagos", debut_year=2018, genres=["afrobeats"]
    )
    song = Song(title="Free Mind", release_date=date(2020, 9, 1))
    song.credits = [SongArtist(artist=tems, role="primary")]
    db.session.add(song)
    db.session.commit()

    data = client.get("/api/v1/artists/tems").get_json()["data"]

    assert data["bio"] == "Singer"
    assert data["debut_year"] == 2018
    assert data["genres"] == [{"name": "Afrobeats", "slug": "afrobeats"}]
    assert data["songs"] == [
        {"id": song.id, "title": "Free Mind", "release_date": "2020-09-01", "role": "primary"}
    ]
    assert data["albums"] == []


def test_detail_404_for_unknown_and_archived(app, client):
    artist = make_artist("Tems")
    artist_service.archive_artist(artist)

    assert client.get("/api/v1/artists/tems").status_code == 404
    assert client.get("/api/v1/artists/nobody").status_code == 404