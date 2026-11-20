import pytest
import sqlalchemy as sa

from app.collectors import lastfm_sync, sync
from app.collectors.http import CollectorError
from app.collectors.lastfm import LastFmClient
from app.extensions import db
from app.models import ArtistExternalId, MetricSnapshot
from app.services import artist_service
from tests.collector_fakes import (
    MBID_A, MBID_B, MBID_C, MBID_D, FakeLastFm, FakeResponse, make_http,
)


def make_client(*responses):
    http, session, _ = make_http(*responses)
    return LastFmClient(http, "secret-key"), session


def artist_payload(mbid=MBID_A, **stats):
    return {"artist": {"name": "Tems", "mbid": mbid, "stats": stats}}


# ---------- the client ----------

def test_listeners_and_playcount_are_parsed():
    client, session = make_client(FakeResponse(200, artist_payload(listeners="1234", playcount="5678")))

    assert client.get_artist_stats(MBID_A) == {"listeners": 1234, "playcount": 5678}

    call = session.calls[0]
    assert call["url"] == "https://ws.audioscrobbler.com/2.0/"
    assert call["params"]["method"] == "artist.getInfo"
    assert call["params"]["mbid"] == MBID_A
    assert call["params"]["api_key"] == "secret-key"
    assert call["params"]["format"] == "json"


def test_the_older_plays_field_is_understood():
    client, _ = make_client(FakeResponse(200, artist_payload(listeners="10", plays="99")))
    assert client.get_artist_stats(MBID_A) == {"listeners": 10, "playcount": 99}


@pytest.mark.parametrize("status", [200, 400, 404])
def test_artist_not_found_is_not_an_error(status):
    body = {"error": 6, "message": "The artist you supplied could not be found"}
    client, _ = make_client(FakeResponse(status, body))
    assert client.get_artist_stats(MBID_A) is None


def test_temporary_errors_raise():
    for code in (11, 16, 29):
        client, _ = make_client(FakeResponse(200, {"error": code, "message": "try later"}))
        with pytest.raises(CollectorError, match="temporarily"):
            client.get_artist_stats(MBID_A)


def test_other_errors_raise_without_leaking_the_key():
    client, _ = make_client(FakeResponse(403, {"error": 10, "message": "Invalid API key"}))
    with pytest.raises(CollectorError) as excinfo:
        client.get_artist_stats(MBID_A)
    assert "10" in str(excinfo.value)
    assert "secret-key" not in str(excinfo.value)


def test_a_different_artist_id_in_the_answer_is_not_trusted():
    client, _ = make_client(FakeResponse(200, artist_payload(mbid=MBID_B, listeners="10")))
    assert client.get_artist_stats(MBID_A) is None


@pytest.mark.parametrize(
    "payload",
    [{}, {"artist": {"mbid": MBID_A}}, artist_payload(listeners="n/a")],
)
def test_incomplete_answers_are_skipped(payload):
    client, _ = make_client(FakeResponse(200, payload))
    assert client.get_artist_stats(MBID_A) is None


def test_invalid_ids_are_refused_before_any_request():
    client, session = make_client()
    with pytest.raises(CollectorError):
        client.get_artist_stats("not-an-id")
    assert session.calls == []


# ---------- the job ----------

def linked_artist(name, mbid):
    artist = artist_service.create_artist({"name": name})
    source = sync.ensure_source()
    db.session.add(
        ArtistExternalId(artist_id=artist.id, data_source_id=source.id, external_id=mbid)
    )
    db.session.commit()
    return artist


def snapshots():
    return db.session.scalars(sa.select(MetricSnapshot).order_by(MetricSnapshot.id)).all()


def test_snapshots_are_recorded_for_linked_artists(app):
    tems = linked_artist("Tems", MBID_A)
    fake = FakeLastFm(stats={MBID_A: {"listeners": 1200, "playcount": 5000}})

    run = lastfm_sync.run_lastfm(fake)

    assert run.status == "succeeded"
    assert (run.items_seen, run.items_created, run.items_skipped, run.items_failed) == (1, 2, 0, 0)
    assert {(s.artist_id, s.metric_type, s.value) for s in snapshots()} == {
        (tems.id, "lastfm_listeners", 1200),
        (tems.id, "lastfm_playcount", 5000),
    }


def test_a_second_run_on_the_same_day_makes_no_requests(app):
    linked_artist("Tems", MBID_A)
    fake = FakeLastFm(stats={MBID_A: {"listeners": 1200, "playcount": 5000}})

    lastfm_sync.run_lastfm(fake)
    second = lastfm_sync.run_lastfm(fake)

    assert fake.requested == [MBID_A]
    assert second.items_seen == 0
    assert len(snapshots()) == 2


def test_unlinked_and_archived_artists_are_not_requested(app):
    artist_service.create_artist({"name": "No Link"})
    gone = linked_artist("Gone", MBID_B)
    artist_service.archive_artist(gone)
    fake = FakeLastFm()

    run = lastfm_sync.run_lastfm(fake)

    assert fake.requested == []
    assert run.items_seen == 0


def test_artists_unknown_to_lastfm_are_skipped(app):
    linked_artist("Tems", MBID_A)
    fake = FakeLastFm(stats={MBID_A: None})

    run = lastfm_sync.run_lastfm(fake)

    assert (run.status, run.items_skipped, run.items_created) == ("succeeded", 1, 0)
    assert snapshots() == []


def test_failures_stop_the_run_after_three(app):
    mbids = [MBID_A, MBID_B, MBID_C, MBID_D]
    for index, mbid in enumerate(mbids):
        linked_artist(f"Artist {index}", mbid)
    fake = FakeLastFm(errors={mbid: CollectorError("down") for mbid in mbids})

    run = lastfm_sync.run_lastfm(fake)

    assert run.status == "failed"
    assert len(fake.requested) == 3
    assert "consecutive" in run.error_summary


def test_a_missing_playcount_still_records_listeners(app):
    linked_artist("Tems", MBID_A)
    fake = FakeLastFm(stats={MBID_A: {"listeners": 1200, "playcount": None}})

    run = lastfm_sync.run_lastfm(fake)

    assert run.items_created == 1
    assert [s.metric_type for s in snapshots()] == ["lastfm_listeners"]