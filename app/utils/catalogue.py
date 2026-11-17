import re
from datetime import date
from urllib.parse import urlparse

from app.errors import ValidationError
from app.utils.validation import slugify

ISRC_RE = re.compile(r"[A-Z]{2}[A-Z0-9]{3}[0-9]{7}")
DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

# Where each kind of link may point. None means "any https site".
PLATFORM_DOMAINS = {
    "spotify": ("open.spotify.com",),
    "apple_music": ("music.apple.com",),
    "youtube": ("youtube.com", "youtu.be"),
    "audiomack": ("audiomack.com",),
    "boomplay": ("boomplay.com",),
    "deezer": ("deezer.com",),
    "soundcloud": ("soundcloud.com",),
    "tidal": ("tidal.com",),
    "website": None,
}


def escape_like(text):
    """Make %, _ and \\ match literally inside LIKE patterns."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def title_key(text):
    """Comparison key for spotting duplicates: 'Calm Down!' == 'calm  down'."""
    return slugify(text) or " ".join(text.lower().split())


def parse_release_date(value, field="release_date"):
    if value is None:
        return None
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        raise ValidationError(f"{field} is invalid.", details={field: "Use the format YYYY-MM-DD."})
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValidationError(
            f"{field} is invalid.", details={field: "This is not a real date."}
        ) from None
    latest = date(date.today().year + 2, 12, 31)  # announced releases are allowed
    if not date(1950, 1, 1) <= parsed <= latest:
        raise ValidationError(
            f"{field} is invalid.",
            details={field: f"Must be between 1950-01-01 and {latest.isoformat()}."},
        )
    return parsed


def normalize_isrc(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError("isrc is invalid.", details={"isrc": "Must be text."})
    cleaned = value.replace("-", "").replace(" ", "").upper()
    if not cleaned:
        return None
    if not ISRC_RE.fullmatch(cleaned):
        raise ValidationError(
            "isrc is invalid.",
            details={"isrc": "An ISRC has 12 characters, for example NGA012200001."},
        )
    return cleaned


def validate_link(platform, url):
    """Return a cleaned (platform, url) pair, or raise ValidationError."""
    allowed = ", ".join(PLATFORM_DOMAINS)
    if not isinstance(platform, str) or platform.strip().lower() not in PLATFORM_DOMAINS:
        raise ValidationError("platform is invalid.", details={"platform": f"Must be one of: {allowed}."})
    platform = platform.strip().lower()

    if not isinstance(url, str):
        raise ValidationError("url is invalid.", details={"url": "Must be text."})
    url = url.strip()
    if not url or len(url) > 500 or any(ch.isspace() for ch in url):
        raise ValidationError(
            "url is invalid.", details={"url": "Enter a link of up to 500 characters, with no spaces."}
        )
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        parsed, host = None, ""
    if parsed is None or parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise ValidationError("url is invalid.", details={"url": "Use a full https:// link."})

    domains = PLATFORM_DOMAINS[platform]
    if domains and not any(host == d or host.endswith("." + d) for d in domains):
        raise ValidationError(
            "url is invalid.", details={"url": f"A {platform} link must be on {' or '.join(domains)}."}
        )
    return platform, url