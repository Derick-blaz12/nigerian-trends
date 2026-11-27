from datetime import timedelta

import pytest
import sqlalchemy as sa

from app.errors import ValidationError
from app.extensions import db
from app.following.rules import FollowRules
from app.models import Notification, NotificationPreference
from app.models.mixins import utcnow
from app.services import (
    artist_service,
    auth_service,
    digest_service,
    follow_service,
    notification_service,
    preference_service,
    song_service,
    update_service,
)

PASSWORD = "correct-horse-battery"


def make_user(number=1):
    return auth_service.register_user(f"fan{number}@example.com", f"fan_{number}", PASSWORD)


def make_artist(name):
    return artist_service.create_artist({"name": name})


def make_song(title, artist):
    return song_service.create_song(
        {
            "title": title,
            "release_date": (utcnow().date() - timedelta(days=1)).isoformat(),
            "artists": [{"artist_id": artist.id, "role": "primary"}],
        }
    )


def publish_news(artist, title):
    update = update_service.create_update(
        {"artist_id": artist.id, "title": title, "body": "A long enough announcement body for publishing."}
    )
    return update_service.publish_update(update)


def all_notifications():
    return db.session.scalars(sa.select(Notification).order_by(Notification.id)).all()


# ---------- preferences ----------

def test_preferences_have_defaults_until_changed(app):
    fan = make_user(1)

    assert preference_service.get_preferences(fan) == {
        "notify_releases": True, "notify_news": True, "email_digest": False,
    }
    assert db.session.get(NotificationPreference, fan.id) is None


def test_preferences_are_updated_partially(app):
    fan = make_user(1)

    first = preference_service.update_preferences(fan, {"email_digest": True})
    assert first == {"notify_releases": True, "notify_news": True, "email_digest": True}

    second = preference_service.update_preferences(fan, {"notify_news": False})
    assert second == {"notify_releases": True, "notify_news": False, "email_digest": True}
    assert db.session.scalar(sa.select(sa.func.count()).select_from(NotificationPreference)) == 1


@pytest.mark.parametrize("data", [{}, {"notify_news": "no"}, {"colour": True}, "text"])
def test_preference_validation(app, data):
    fan = make_user(1)
    with pytest.raises(ValidationError):
        preference_service.update_preferences(fan, data)


# ---------- the digest preview ----------

def test_there_is_no_digest_without_unread_notifications(app):
    assert digest_service.build_digest(make_user(1)) is None


def test_the_digest_lists_new_items(app):
    fan, tems = make_user(1), make_artist("Tems")
    follow_service.follow_artist(fan, "tems")
    make_song("Free Mind", tems)
    notification_service.generate_notifications()

    one = digest_service.build_digest(fan)
    assert one["subject"] == "1 new thing from artists you follow"
    assert (one["count"], one["shown"]) == (1, 1)
    assert 'Tems: new song "Free Mind"' in one["body"]

    publish_news(tems, "Big news")
    notification_service.generate_notifications()

    two = digest_service.build_digest(fan)
    assert two["subject"] == "2 new things from artists you follow"
    assert 'Tems: news "Big news"' in two["body"]
    assert "Hi fan_1," in two["body"]
    assert "http://127.0.0.1:5000/notifications" in two["body"]


def test_the_digest_is_capped(app):
    fan, tems = make_user(1), make_artist("Tems")
    follow_service.follow_artist(fan, "tems")
    for title in ("One", "Two", "Three"):
        make_song(title, tems)
    notification_service.generate_notifications()

    digest = digest_service.build_digest(fan, rules=FollowRules(digest_max_items=2))

    assert (digest["count"], digest["shown"]) == (3, 2)
    assert "...and 1 more" in digest["body"]


def test_the_digest_skips_read_and_old_notifications(app):
    fan, tems = make_user(1), make_artist("Tems")
    follow_service.follow_artist(fan, "tems")
    make_song("One", tems)
    make_song("Two", tems)
    notification_service.generate_notifications()
    first, second = all_notifications()

    notification_service.mark_read(fan, first.id)
    assert digest_service.build_digest(fan)["count"] == 1

    second.created_at = utcnow() - timedelta(days=8)
    db.session.commit()
    assert digest_service.build_digest(fan) is None