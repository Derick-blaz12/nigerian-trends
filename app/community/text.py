import re

from app.errors import ValidationError

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BLANK_LINES = re.compile(r"\n{3,}")
_LINK = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)


def clean_comment_body(value, rules):
    """Return tidy comment text, or raise ValidationError."""
    if not isinstance(value, str):
        raise ValidationError("body is required.", details={"body": "Write something first."})
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", text).strip()
    text = _BLANK_LINES.sub("\n\n", text)
    if not text:
        raise ValidationError("body is required.", details={"body": "Write something first."})
    if len(text) > rules.comment_max_length:
        raise ValidationError(
            "body is too long.",
            details={"body": f"At most {rules.comment_max_length} characters."},
        )
    if len(_LINK.findall(text)) > rules.max_links_per_comment:
        raise ValidationError(
            "body has too many links.",
            details={"body": f"At most {rules.max_links_per_comment} links per comment."},
        )
    return text


def normalize_for_compare(text):
    """'  Great   SONG ' and 'great song' count as the same text."""
    return " ".join(text.lower().split())