import re
import unicodedata

from app.errors import ValidationError

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def require_fields(data, fields):
    """Ensure `data` is a JSON object containing every field in `fields`."""
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object.")
    missing = [f for f in fields if data.get(f) in (None, "")]
    if missing:
        raise ValidationError(
            "Missing required fields.",
            details={f: "This field is required." for f in missing},
        )


def clean_string(value, field, min_len=1, max_len=255):
    """Return a stripped string, or raise ValidationError."""
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be text.", details={field: "Must be text."})
    value = value.strip()
    if not (min_len <= len(value) <= max_len):
        message = f"Must be between {min_len} and {max_len} characters."
        raise ValidationError(f"{field} is invalid.", details={field: message})
    return value


def parse_int(value, field, default, minimum=1, maximum=None):
    """Parse an integer from user input (e.g. a query parameter)."""
    if value is None or value == "":
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValidationError(
            f"{field} is invalid.", details={field: "Must be a whole number."}
        ) from None
    if number < minimum or (maximum is not None and number > maximum):
        upper = f" and {maximum}" if maximum is not None else " or more"
        raise ValidationError(
            f"{field} is out of range.", details={field: f"Must be between {minimum}{upper}."}
        )
    return number


def is_valid_email(value):
    return isinstance(value, str) and bool(_EMAIL_RE.match(value))


def slugify(text):
    """'Alté Café!' -> 'alte-cafe'. Handles accented characters."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")