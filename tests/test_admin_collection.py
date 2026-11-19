import sqlalchemy as sa

from app.collectors import sync
from app.extensions import db
from app.models import ArtistExternalId, MatchCandidate
from app.services import artist_service
from tests.collector_fakes import MBID_A, MBID_B, FakeMusicBrainz

ADMIN = "/api/v1/admin"


def make_candidate(artist, mbid=MBID_A, status="pending"):
    source = sync.ensure_source()
    candidate = MatchCandidate(
        artist_id=artist.id, data_source_id=source.id, external_id=mbid,
        external_name=artist.name, country="NG", score=95, status=status,
    )
    db.session.add(candidate)
    db.session.commit()
    return candidate


def test_collection_routes_require_an_admin(app, client, user_client):
    calls = [
        ("get", f"{ADMIN}/match-candidates"),
        ("post", f"{ADMIN}/match-candidates/1/confirm"),
        ("post", f"{ADMIN}/match-candidates/1/reject"),
        ("get", f"{ADMIN}/collection-runs"),
    ]
    for method, url in calls:
        assert getattr(client, method)(url, json={}).status_code == 401, (method, url)
        assert getattr(user_client, method)(url, json={}).status_code == 403, (method, url)


def test_list_candidates_by_status(admin_client):
    artist = artist_service.create_artist({"name": "Tems"})
    make_candidate(artist, MBID_A)
    make_candidate(artist, MBID_B, status="rejected")

    body = admin_client.get(f"{ADMIN}/match-candidates").get_json()
    assert body["meta"]["total"] == 1
    item = body["data"][0]
    assert item["status"] == "pending"
    assert item["artist"] == {"id": artist.id, "name": "Tems", "slug": "tems"}
    assert item["candidate"]["url"] == f"https://musicbrainz.org/artist/{MBID_A}"

    rejected = admin_client.get(f"{ADMIN}/match-candidates?status=rejected").get_json()
    assert [c["candidate"]["musicbrainz_id"] for c in rejected["data"]] == [MBID_B]
    assert admin_client.get(f"{ADMIN}/match-candidates?status=bogus").status_code == 422


def test_confirming_links_the_artist_and_rejects_the_alternatives(admin_client):
    artist = artist_service.create_artist({"name": "Tems"})
    first = make_candidate(artist, MBID_A)
    second = make_candidate(artist, MBID_B)

    response = admin_client.post(f"{ADMIN}/match-candidates/{first.id}/confirm")

    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == "confirmed"
    (link,) = db.session.scalars(sa.select(ArtistExternalId)).all()
    assert (link.artist_id, link.external_id, link.last_synced_at) == (artist.id, MBID_A, None)
    assert db.session.get(MatchCandidate, second.id).status == "rejected"

    assert admin_client.post(f"{ADMIN}/match-candidates/{first.id}/confirm").status_code == 409
    assert admin_client.post(f"{ADMIN}/match-candidates/{second.id}/confirm").status_code == 409
    assert admin_client.post(f"{ADMIN}/match-candidates/999999/confirm").status_code == 404


def test_confirming_refuses_an_id_linked_to_another_artist(admin_client):
    owner = artist_service.create_artist({"name": "Tems"})
    other = artist_service.create_artist({"name": "Tems!"})
    source = sync.ensure_source()
    db.session.add(ArtistExternalId(artist_id=owner.id, data_source_id=source.id, external_id=MBID_A))
    db.session.commit()
    candidate = make_candidate(other, MBID_A)

    response = admin_client.post(f"{ADMIN}/match-candidates/{candidate.id}/confirm")

    assert response.status_code == 409
    assert db.session.get(MatchCandidate, candidate.id).status == "pending"


def test_rejecting_a_candidate(admin_client):
    artist = artist_service.create_artist({"name": "Tems"})
    candidate = make_candidate(artist)

    response = admin_client.post(f"{ADMIN}/match-candidates/{candidate.id}/reject")

    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == "rejected"
    assert admin_client.post(f"{ADMIN}/match-candidates/{candidate.id}/reject").status_code == 409
    assert admin_client.post(f"{ADMIN}/match-candidates/999999/reject").status_code == 404


def test_collection_runs_are_listed_newest_first(admin_client):
    sync.run_musicbrainz(FakeMusicBrainz(), triggered_by="cli")
    sync.run_musicbrainz(FakeMusicBrainz(), triggered_by="schedule")

    body = admin_client.get(f"{ADMIN}/collection-runs").get_json()

    assert body["meta"]["total"] == 2
    newest = body["data"][0]
    assert newest["triggered_by"] == "schedule"
    assert newest["source"] == "MusicBrainz"
    assert newest["status"] == "succeeded"
    assert set(newest["items"]) == {"seen", "created", "updated", "skipped", "failed"}