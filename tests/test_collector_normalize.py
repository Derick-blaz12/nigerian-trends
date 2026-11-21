from datetime import date

import pytest

from app.collectors.normalize import (
    detect_link,
    is_mbid,
    normalize_artist_detail,
    normalize_artist_hit,
    normalize_release_group,
    normalize_single,
    parse_mb_date,
)
from tests.collector_fakes import MBID_A, MBID_B


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2021-03-25", (2021, date(2021, 3, 25))),
        ("2021-03", (2021, None)),
        ("2021", (2021, None)),
        ("2021-02-30", (2021, None)),
        ("", (None, None)),
        (None, (None, None)),
        ("1900", (None, None)),
        ("2099", (None, None)),
        ("March 2021", (None, None)),
    ],
)
def test_parse_mb_date(value, expected):
    assert parse_mb_date(value) == expected


def test_is_mbid():
    assert is_mbid(MBID_A)
    assert is_mbid("abcdef01-2345-4789-8abc-def012345678")
    assert not is_mbid("not-an-id")
    assert not is_mbid(None)
    assert not is_mbid("ABCDEF01-2345-4789-8ABC-DEF012345678")  # MusicBrainz ids are lowercase
    

def raw_group(**overrides):
    data = {
        "id": MBID_B,
        "title": "Born in the Wild",
        "primary-type": "Album",
        "secondary-types": [],
        "first-release-date": "2024-06-07",
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize("primary, expected", [("Album", "album"), ("EP", "ep")])
def test_release_groups_are_normalized(primary, expected):
    result = normalize_release_group(raw_group(**{"primary-type": primary}))
    assert result == {
        "mbid": MBID_B,
        "title": "Born in the Wild",
        "album_type": expected,
        "year": 2024,
        "release_date": date(2024, 6, 7),
    }


def test_singles_are_not_imported():
    assert normalize_release_group(raw_group(**{"primary-type": "Single"})) is None
    
def test_singles_are_not_imported():
    assert normalize_release_group(raw_group(**{"primary-type": "Single"})) is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"secondary-types": ["Live"]},
        {"primary-type": "Broadcast"},
        {"id": "not-an-id"},
        {"title": "   "},
        {"primary-type": None},
    ],
)
def test_unusable_release_groups_are_skipped(overrides):
    assert normalize_release_group(raw_group(**overrides)) is None


def test_partial_or_missing_release_dates_stay_missing():
    year_only = normalize_release_group(raw_group(**{"first-release-date": "2021"}))
    assert (year_only["year"], year_only["release_date"]) == (2021, None)

    blank = normalize_release_group(raw_group(**{"first-release-date": ""}))
    assert (blank["year"], blank["release_date"]) == (None, None)


@pytest.mark.parametrize(
    "rel_type, url, expected",
    [
        ("streaming music", "https://open.spotify.com/artist/abc", ("spotify", "https://open.spotify.com/artist/abc")),
        ("youtube", "https://www.youtube.com/@tems", ("youtube", "https://www.youtube.com/@tems")),
        ("official homepage", "https://tems.example/", ("website", "https://tems.example/")),
    ],
)
def test_known_links_are_detected(rel_type, url, expected):
    assert detect_link(rel_type, url) == expected


@pytest.mark.parametrize(
    "rel_type, url",
    [
        ("social network", "https://www.facebook.com/tems"),
        ("official homepage", "http://tems.example/"),
        ("streaming music", "http://open.spotify.com/artist/abc"),
        ("official homepage", "not a url"),
    ],
)
def test_unknown_or_unsafe_links_are_dropped(rel_type, url):
    assert detect_link(rel_type, url) is None


def test_artist_hit_is_cleaned():
    raw = {
        "id": MBID_A, "name": "Tems", "country": "ng", "score": 100,
        "life-span": {"begin": "1995-06-11"}, "disambiguation": " singer ",
    }
    assert normalize_artist_hit(raw) == {
        "mbid": MBID_A, "name": "Tems", "country": "NG", "disambiguation": "singer",
        "begin_year": 1995, "score": 100,
    }


def test_artist_hit_with_a_bad_id_is_dropped():
    assert normalize_artist_hit({"id": "nope", "name": "Tems"}) is None
    assert normalize_artist_hit("not a dict") is None


def test_artist_hit_without_a_country_keeps_it_empty():
    hit = normalize_artist_hit({"id": MBID_A, "name": "Tems"})
    assert hit["country"] is None
    assert hit["score"] == 0


def test_artist_detail_keeps_only_valid_unique_links():
    raw = {
        "relations": [
            {"type": "streaming music", "target-type": "url",
             "url": {"resource": "https://open.spotify.com/artist/abc"}},
            {"type": "streaming music", "target-type": "url",
             "url": {"resource": "https://open.spotify.com/artist/abc"}},
            {"type": "member of band", "target-type": "artist", "artist": {"name": "Someone"}},
            {"type": "official homepage", "target-type": "url",
             "url": {"resource": "https://tems.example/"}},
            {"type": "social network", "target-type": "url",
             "url": {"resource": "https://www.facebook.com/tems"}},
        ]
    }
    assert normalize_artist_detail(raw) == {
        "links": [
            ("spotify", "https://open.spotify.com/artist/abc"),
            ("website", "https://tems.example/"),
        ]
    }

def test_plain_singles_are_normalized():
    result = normalize_single(raw_group(**{"primary-type": "Single", "title": "Higher"}))
    assert result == {
        "mbid": MBID_B, "title": "Higher", "year": 2024, "release_date": date(2024, 6, 7),
    }


@pytest.mark.parametrize(
    "overrides",
    [{"primary-type": "Album"}, {"secondary-types": ["Remix"]}, {"title": "  "}, {"id": "nope"}],
)
def test_only_plain_singles_are_accepted(overrides):
    data = {"primary-type": "Single"}
    data.update(overrides)
    assert normalize_single(raw_group(**data)) is None