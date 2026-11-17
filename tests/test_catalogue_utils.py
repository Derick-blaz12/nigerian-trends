from datetime import date

import pytest

from app.errors import ValidationError
from app.utils.catalogue import normalize_isrc, parse_release_date, title_key, validate_link


def test_title_key_ignores_case_punctuation_and_accents():
    assert title_key("Calm Down!") == title_key("  calm   DOWN")
    assert title_key("Alté") == "alte"
    assert title_key("Calm Down (Remix)") != title_key("Calm Down")


def test_parse_release_date_accepts_real_dates():
    assert parse_release_date("2022-02-11") == date(2022, 2, 11)
    assert parse_release_date(None) is None


@pytest.mark.parametrize(
    "value",
    ["2022/02/11", "2022-13-01", "2022-02-30", 20220211, "1900-01-01", "2999-01-01"],
)
def test_parse_release_date_rejects_bad_values(value):
    with pytest.raises(ValidationError):
        parse_release_date(value)


def test_normalize_isrc_cleans_input():
    assert normalize_isrc(" ng-a01-22-00001 ") == "NGA012200001"
    assert normalize_isrc(None) is None
    assert normalize_isrc("") is None


@pytest.mark.parametrize("value", ["TOOSHORT", "NGA01220000X", 12345])
def test_normalize_isrc_rejects_bad_values(value):
    with pytest.raises(ValidationError):
        normalize_isrc(value)


def test_validate_link_accepts_matching_platforms():
    assert validate_link("spotify", "https://open.spotify.com/track/abc") == (
        "spotify", "https://open.spotify.com/track/abc",
    )
    assert validate_link(" YouTube ", "https://www.youtube.com/watch?v=1")[0] == "youtube"
    assert validate_link("website", "https://tems.example/")[0] == "website"


@pytest.mark.parametrize(
    "platform, url",
    [
        ("spotify", "http://open.spotify.com/track/abc"),
        ("spotify", "https://open.spotify.com.evil.com/x"),
        ("spotify", "https://evil.example/x"),
        ("spotify", "javascript:alert(1)"),
        ("spotify", "https://user:pw@open.spotify.com/x"),
        ("tiktok", "https://tiktok.com/x"),
        ("spotify", "https://open.spotify.com/a b"),
    ],
)
def test_validate_link_rejects_bad_links(platform, url):
    with pytest.raises(ValidationError):
        validate_link(platform, url)