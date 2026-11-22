from datetime import timedelta

import pytest

from app.community.guard import ensure_can_post
from app.community.rules import DEFAULT_RULES, rules_as_dict
from app.community.scoring import popularity_score
from app.community.text import clean_comment_body, normalize_for_compare
from app.errors import ForbiddenError, ValidationError
from app.models import User
from app.models.mixins import utcnow


def test_the_score_adds_up_the_weights():
    assert popularity_score(likes=10, recommends=2, commenters=3) == 10 + 6 + 6
    assert popularity_score(0, 0, 0) == 0


def test_a_recommendation_outweighs_a_like():
    assert popularity_score(0, 1, 0) > popularity_score(1, 0, 0)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("  hello  ", "hello"),
        ("a\r\nb", "a\nb"),
        ("a\n\n\n\nb", "a\n\nb"),
        ("he\x00llo\x07", "hello"),
    ],
)
def test_comment_text_is_cleaned(raw, expected):
    assert clean_comment_body(raw, DEFAULT_RULES) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   \n ",
        None,
        42,
        "x" * 2001,
        "see http://a.example and https://b.example and www.c.example",
    ],
)
def test_unusable_comment_text_is_rejected(raw):
    with pytest.raises(ValidationError):
        clean_comment_body(raw, DEFAULT_RULES)


def test_two_links_are_allowed_and_a_www_url_counts_once():
    text = "https://www.a.example and https://www.b.example"
    assert clean_comment_body(text, DEFAULT_RULES) == text


def test_comparison_ignores_case_and_spacing():
    assert normalize_for_compare("  Great   SONG ") == "great song"


def test_the_rules_are_plain_data():
    data = rules_as_dict()
    assert data["recommend_points"] == 3
    assert data["min_engaged_users"] == 3


def test_muted_users_cannot_post():
    user = User(email="a@example.com", username="a_user", password_hash="x")
    ensure_can_post(user)

    user.muted_until = utcnow() + timedelta(days=1)
    with pytest.raises(ForbiddenError) as excinfo:
        ensure_can_post(user)
    assert excinfo.value.code == "muted"

    user.muted_until = utcnow() - timedelta(days=1)
    ensure_can_post(user)