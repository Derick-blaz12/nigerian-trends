import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Notification, NotificationPreference
from app.services import artist_service, auth_service

PASSWORD = "correct-horse-battery"


def make_user(number):
    return auth_service.register_user(f"fan{number}@example.com", f"fan_{number}", PASSWORD)


def test_a_notification_is_unique_per_person_kind_and_item(app):
    fan = make_user(1)
    tems = artist_service.create_artist({"name": "Tems"})
    db.session.add(Notification(user_id=fan.id, artist_id=tems.id, kind="song", item_id=1))
    db.session.commit()

    db.session.add(Notification(user_id=fan.id, artist_id=tems.id, kind="song", item_id=1))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    db.session.add(Notification(user_id=fan.id, artist_id=tems.id, kind="news", item_id=1))
    db.session.commit()  # the same id with a different kind is a different item


def test_notification_kinds_are_restricted(app):
    fan = make_user(1)
    tems = artist_service.create_artist({"name": "Tems"})
    db.session.add(Notification(user_id=fan.id, artist_id=tems.id, kind="gossip", item_id=1))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_notification_preferences_have_sensible_defaults(app):
    fan = make_user(1)
    db.session.add(NotificationPreference(user_id=fan.id))
    db.session.commit()

    pref = db.session.get(NotificationPreference, fan.id)
    assert (pref.notify_releases, pref.notify_news, pref.email_digest) == (True, True, False)
    assert pref.updated_at is not None