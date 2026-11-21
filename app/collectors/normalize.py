import re
from datetime import date
from urllib.parse import urlparse

from app.errors import ValidationError
from app.utils.catalogue import PLATFORM_DOMAINS, parse_release_date, validate_link
from app.utils.validation import clean_string

MBID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_DATE_RE = re.compile(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?")
RELEASE_TYPES = {"Album": "album", "EP": "ep"}

def is_mbid(value):
    return isinstance(value, str) and MBID_RE.fullmatch(value) is not None


def parse_mb_date(value):
    """MusicBrainz dates may be partial ('2021', '2021-03'). Returns (year, full_date)."""
    if not isinstance(value, str):
        return None, None
    value = value.strip()
    match = _DATE_RE.fullmatch(value)
    if not match:
        return None, None
    year = int(match.group(1))
    if not 1950 <= year <= date.today().year + 2:
        return None, None
    full = None
    if match.group(3):
        try:
            full = parse_release_date(value)
        except ValidationError:
            full = None
    return year, full


def normalize_artist_hit(raw):
    """A search result becomes a small, validated dict, or None if it's unusable."""
    if not isinstance(raw, dict) or not is_mbid(raw.get("id")):
        return None
    try:
        name = clean_string(raw.get("name"), "name", min_len=1, max_len=200)
    except ValidationError:
        return None

    country = raw.get("country")
    country = country.upper() if isinstance(country, str) and len(country) == 2 else None
    life_span = raw.get("life-span") if isinstance(raw.get("life-span"), dict) else {}
    begin_year, _ = parse_mb_date(life_span.get("begin"))
    disambiguation = raw.get("disambiguation")
    disambiguation = (
        disambiguation.strip()[:300]
        if isinstance(disambiguation, str) and disambiguation.strip()
        else None
    )
    score = raw.get("score")
    score = int(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else 0
    return {
        "mbid": raw["id"],
        "name": name,
        "country": country,
        "disambiguation": disambiguation,
        "begin_year": begin_year,
        "score": score,
    }


def normalize_release_group(raw):
    """Keep plain albums, EPs and singles. Skip live, remix, compilation and similar."""
    if not isinstance(raw, dict) or not is_mbid(raw.get("id")):
        return None
    album_type = RELEASE_TYPES.get(raw.get("primary-type"))
    if album_type is None or raw.get("secondary-types"):
        return None
    try:
        title = clean_string(raw.get("title"), "title", min_len=1, max_len=200)
    except ValidationError:
        return None
    year, full_date = parse_mb_date(raw.get("first-release-date"))
    return {
        "mbid": raw["id"],
        "title": title,
        "album_type": album_type,
        "year": year,
        "release_date": full_date,
    }


def detect_link(rel_type, url):
    """Turn a MusicBrainz URL relationship into a validated (platform, url), or None."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return None
    platform = None
    for name, domains in PLATFORM_DOMAINS.items():
        if domains and any(host == d or host.endswith("." + d) for d in domains):
            platform = name
            break
    if platform is None and rel_type == "official homepage":
        platform = "website"
    if platform is None:
        return None
    try:
        return validate_link(platform, url)
    except ValidationError:
        return None


def normalize_artist_detail(raw):
    links = []
    for relation in raw.get("relations") or []:
        if not isinstance(relation, dict):
            continue
        url = (relation.get("url") or {}).get("resource")
        if not isinstance(url, str):
            continue
        link = detect_link(relation.get("type"), url)
        if link and link not in links:
            links.append(link)
    return {"links": links}

def normalize_single(raw):
    """A plain single (no remix, live or other secondary type) becomes a song to import."""
    if not isinstance(raw, dict) or not is_mbid(raw.get("id")):
        return None
    if raw.get("primary-type") != "Single" or raw.get("secondary-types"):
        return None
    try:
        title = clean_string(raw.get("title"), "title", min_len=1, max_len=200)
    except ValidationError:
        return None
    year, full_date = parse_mb_date(raw.get("first-release-date"))
    return {"mbid": raw["id"], "title": title, "year": year, "release_date": full_date}