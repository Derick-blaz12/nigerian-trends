import pytest

from app.errors import ValidationError
from app.utils.validation import clean_string, is_valid_email, parse_int, require_fields, slugify


def test_slugify_basic():
    assert slugify("Afro Fusion!") == "afro-fusion"


def test_slugify_removes_accents():
    assert slugify("Alté Café") == "alte-cafe"


def test_clean_string_strips_whitespace():
    assert clean_string("  Afrobeats  ", "name") == "Afrobeats"


def test_clean_string_rejects_too_short():
    with pytest.raises(ValidationError):
        clean_string("a", "name", min_len=2, max_len=60)


def test_parse_int_uses_default_when_missing():
    assert parse_int(None, "page", default=1) == 1


def test_parse_int_rejects_text():
    with pytest.raises(ValidationError):
        parse_int("abc", "page", default=1)


def test_parse_int_rejects_out_of_range():
    with pytest.raises(ValidationError):
        parse_int("500", "per_page", default=20, maximum=100)


def test_require_fields_reports_every_missing_field():
    with pytest.raises(ValidationError) as exc:
        require_fields({"a": 1}, ["a", "b", "c"])
    assert set(exc.value.details) == {"b", "c"}


def test_is_valid_email():
    assert is_valid_email("ade@example.com")
    assert not is_valid_email("not-an-email")
    assert not is_valid_email("ade@example")