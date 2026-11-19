from datetime import date, timedelta

import pytest
import sqlalchemy as sa

from app.collectors import sync
from app.collectors.http import BudgetExceeded, CollectorError
from app.collectors.runs import RunAlreadyActive
from app.extensions import db
from app.models import Album, ArtistExternalId, CollectionRun, MatchCandidate
from app.models.mixins import utcnow
from app.services import artist_service, collection_service, link_service
from tests.collector_fakes import MBID_A, MBID_B, FakeMusicBrainz, group, hit


def make_artist(name, **extra):
    return artist_service.create_artist({"name": name, **extra})


def link_artist(artist, mbid=MBID_A, synced=None):
    source = sync.ensure_source()
    link = ArtistExternalId(
        artist_id=artist.id, data_source_id=source.id, external_id=mbid, last_synced_at=synced
    )
    db.session.add(link)
    db.session.commit()
    return link


def all_links():
    return db.session.scalars(sa.select(ArtistExternalId)).all()


def pending():
    return db.session.scalars(
        sa.select(MatchCandidate).where(MatchCandidate.status == "pending")
    ).all()


LINKS = [
    ("spotify", "https://open.spotify.com/artist/abc"),
    ("website", "https://tems.example/"),
    ("youtube", "https://www.youtube.com/@tems"),
]
GROUPS = [
    group("Born in the Wild", "album", 2024, date(2024, 6, 7)),
    group("For Broken Ears", "ep", 2020),
    group("Higher", "single", 2019, date(2019, 8, 1)),
]


# ---------- linking ----------

def test_source_is_created_once(app):
    first, second = sync.ensure_source(), sync.ensure_source()
    assert first.id == second.id
    assert first.name == "MusicBrainz"
    assert first.terms_url.startswith("https://musicbrainz.org/")


def test_single_nigerian_exact_match_is_linked(app):
    artist = make_artist("Tems")
    mb = FakeMusicBrainz(hits={"Tems": [hit("Tems")]})

    run = sync.run_musicbrainz(mb, enrich=False)

    (link,) = all_links()
    assert (link.artist_id, link.external_id) == (artist.id, MBID_A)
    assert run.status == "succeeded"
    assert (run.items_seen, run.items_created, run.items_skipped, run.items_failed) == (1, 1, 0, 0)
    assert run.requests_made == 1
    assert run.finished_at is not None


def test_ambiguous_exact_matches_wait_for_review_and_are_not_searched_again(app):
    make_artist("Tems")
    mb = FakeMusicBrainz(hits={"Tems": [hit("Tems", mbid=MBID_A), hit("Tems", mbid=MBID_B)]})

    run = sync.run_musicbrainz(mb, enrich=False)

    assert all_links() == []
    assert sorted(c.external_id for c in pending()) == [MBID_A, MBID_B]
    assert (run.items_created, run.items_skipped) == (0, 1)

    sync.run_musicbrainz(mb, enrich=False)
    assert mb.searched == ["Tems"]


@pytest.mark.parametrize("country", ["GB", None])
def test_exact_match_outside_nigeria_or_without_country_is_reviewed(app, country):
    make_artist("Tems")
    mb = FakeMusicBrainz(hits={"Tems": [hit("Tems", country=country)]})

    sync.run_musicbrainz(mb, enrich=False)

    assert all_links() == []
    assert len(pending()) == 1


def test_nigerian_near_match_is_reviewed(app):
    make_artist("Tems")
    mb = FakeMusicBrainz(hits={"Tems": [hit("Temz", score=90)]})
    sync.run_musicbrainz(mb, enrich=False)
    assert [c.external_name for c in pending()] == ["Temz"]


def test_weak_non_exact_hits_are_ignored(app):
    make_artist("Tems")
    mb = FakeMusicBrainz(hits={"Tems": [hit("Tem Z", score=60), hit("Other", country="GB")]})
    sync.run_musicbrainz(mb, enrich=False)
    assert pending() == []
    assert db.session.scalar(sa.select(MatchCandidate.status)) == "no_match"


def test_no_match_is_remembered_then_retried_after_30_days(app):
    make_artist("Obscure Act")
    mb = FakeMusicBrainz()

    sync.run_musicbrainz(mb, enrich=False)
    sync.run_musicbrainz(mb, enrich=False)
    assert mb.searched == ["Obscure Act"]

    sentinel = db.session.scalar(sa.select(MatchCandidate))
    assert sentinel.status == "no_match" and sentinel.external_id is None
    sentinel.created_at = utcnow() - timedelta(days=31)
    db.session.commit()

    sync.run_musicbrainz(mb, enrich=False)
    assert mb.searched == ["Obscure Act", "Obscure Act"]
    assert db.session.scalar(sa.select(sa.func.count()).select_from(MatchCandidate)) == 1


def test_rejected_candidates_are_never_suggested_again(app):
    make_artist("Tems")
    mb = FakeMusicBrainz(hits={"Tems": [hit("Tems", country="GB")]})
    sync.run_musicbrainz(mb, enrich=False)

    candidate = db.session.scalar(sa.select(MatchCandidate))
    collection_service.reject_candidate(candidate.id)
    sync.run_musicbrainz(mb, enrich=False)

    statuses = sorted(c.status for c in db.session.scalars(sa.select(MatchCandidate)))
    assert statuses == ["no_match", "rejected"]
    assert mb.searched == ["Tems", "Tems"]


def test_an_id_already_linked_to_another_artist_goes_to_review(app):
    make_artist("Tems")
    second = make_artist("Tems!")
    mb = FakeMusicBrainz(hits={"Tems": [hit("Tems")], "Tems!": [hit("Tems")]})

    run = sync.run_musicbrainz(mb, enrich=False)

    assert len(all_links()) == 1
    assert [(c.artist_id, c.external_id) for c in pending()] == [(second.id, MBID_A)]
    assert (run.items_created, run.items_skipped) == (1, 1)


def test_run_stops_after_three_consecutive_failures(app):
    names = ["A One", "B Two", "C Three", "D Four"]
    for name in names:
        make_artist(name)
    mb = FakeMusicBrainz(errors={name: CollectorError("down") for name in names})

    run = sync.run_musicbrainz(mb, enrich=False)

    assert run.status == "failed"
    assert len(mb.searched) == 3
    assert run.items_failed == 3
    assert "consecutive" in run.error_summary


def test_budget_exhaustion_keeps_the_progress_made(app):
    make_artist("A One")
    make_artist("B Two")
    mb = FakeMusicBrainz(
        hits={"A One": [hit("A One")]}, errors={"B Two": BudgetExceeded("budget")}
    )

    run = sync.run_musicbrainz(mb, enrich=False)

    assert run.status == "partial"
    assert "budget" in run.error_summary.lower()
    assert len(all_links()) == 1


def test_overlapping_runs_are_refused_but_stale_runs_are_cleared(app):
    source = sync.ensure_source()
    stuck = CollectionRun(
        data_source_id=source.id, job=sync.JOB, status="running",
        started_at=utcnow() - timedelta(minutes=5),
    )
    db.session.add(stuck)
    db.session.commit()

    with pytest.raises(RunAlreadyActive):
        sync.run_musicbrainz(FakeMusicBrainz())

    stuck.started_at = utcnow() - timedelta(hours=3)
    db.session.commit()
    run = sync.run_musicbrainz(FakeMusicBrainz())

    assert run.status == "succeeded"
    assert db.session.get(CollectionRun, stuck.id).status == "failed"


# ---------- enrichment ----------

def test_enrichment_adds_links_albums_and_a_debut_year(app):
    artist = make_artist("Tems")
    link = link_artist(artist)
    mb = FakeMusicBrainz(details={MBID_A: {"links": LINKS}}, groups={MBID_A: GROUPS})

    run = sync.run_musicbrainz(mb, link=False)

    albums = {
        a.title: (a.album_type, a.release_date)
        for a in db.session.scalars(sa.select(Album).where(Album.artist_id == artist.id))
    }
    assert albums == {
        "Born in the Wild": ("album", date(2024, 6, 7)),
        "For Broken Ears": ("ep", None),
        "Higher": ("single", date(2019, 8, 1)),
    }
    assert artist.debut_year == 2019
    assert sorted(l.platform for l in link_service.list_links("artist", artist.id)) == [
        "spotify", "website", "youtube",
    ]
    assert db.session.get(ArtistExternalId, link.id).last_synced_at is not None
    assert run.status == "succeeded"
    assert (run.items_created, run.items_updated) == (6, 1)


def test_enrichment_only_fills_gaps(app):
    artist = make_artist("Tems", debut_year=2015)
    link_artist(artist)
    dated = Album(artist_id=artist.id, title="Born in the Wild", album_type="album",
                  release_date=date(2024, 1, 1))
    undated = Album(artist_id=artist.id, title="for broken ears!", album_type="ep")
    db.session.add_all([dated, undated])
    db.session.commit()
    mb = FakeMusicBrainz(
        details={MBID_A: {"links": []}},
        groups={MBID_A: [
            group("Born in the Wild", "album", 2024, date(2024, 6, 7)),
            group("For Broken Ears", "ep", 2020, date(2020, 7, 24)),
        ]},
    )

    sync.run_musicbrainz(mb, link=False)

    db.session.expire_all()
    assert db.session.scalar(sa.select(sa.func.count()).select_from(Album)) == 2
    assert dated.release_date == date(2024, 1, 1)
    assert undated.release_date == date(2020, 7, 24)
    assert undated.title == "for broken ears!"
    assert artist.debut_year == 2015


def test_enrichment_is_idempotent(app):
    artist = make_artist("Tems")
    link = link_artist(artist)
    mb = FakeMusicBrainz(details={MBID_A: {"links": LINKS}}, groups={MBID_A: GROUPS})
    sync.run_musicbrainz(mb, link=False)

    link.last_synced_at = utcnow() - timedelta(days=40)
    db.session.commit()
    run = sync.run_musicbrainz(mb, link=False)

    assert run.items_created == 0
    assert db.session.scalar(sa.select(sa.func.count()).select_from(Album)) == 3
    assert len(link_service.list_links("artist", artist.id)) == 3


def test_recently_synced_artists_are_skipped(app):
    link_artist(make_artist("Tems"), synced=utcnow() - timedelta(days=2))
    mb = FakeMusicBrainz()

    run = sync.run_musicbrainz(mb, link=False)

    assert mb.requests_made == 0
    assert run.items_seen == 0


def test_archived_artists_are_ignored(app):
    artist = make_artist("Tems")
    link_artist(artist)
    artist_service.archive_artist(artist)

    run = sync.run_musicbrainz(FakeMusicBrainz())

    assert run.items_seen == 0


def test_artist_missing_from_musicbrainz_is_reported_not_fatal(app):
    link = link_artist(make_artist("Tems"))
    mb = FakeMusicBrainz(details={MBID_A: None})

    run = sync.run_musicbrainz(mb, link=False)

    assert (run.status, run.items_failed) == ("partial", 1)
    assert "no longer has" in run.error_summary
    assert db.session.get(ArtistExternalId, link.id).last_synced_at is not None


def test_temporary_errors_leave_the_artist_for_the_next_run(app):
    link = link_artist(make_artist("Tems"))
    mb = FakeMusicBrainz(errors={MBID_A: CollectorError("temporary")})

    run = sync.run_musicbrainz(mb, link=False)

    assert run.status == "partial"
    assert db.session.get(ArtistExternalId, link.id).last_synced_at is None


def test_year_only_release_still_gives_a_debut_year(app):
    artist = make_artist("Tems")
    link_artist(artist)
    mb = FakeMusicBrainz(
        details={MBID_A: {"links": []}},
        groups={MBID_A: [group("Old Tape", "album", 2021)]},
    )

    sync.run_musicbrainz(mb, link=False)

    album = db.session.scalar(sa.select(Album))
    assert album.release_date is None
    assert artist.debut_year == 2021