from datetime import timedelta

import pytest
import sqlalchemy as sa

from app.errors import NotFoundError
from app.extensions import db
from app.models import Notification
from app.models.mixins import utcnow
from app.services import (
    album_service,
    artist_service,
    auth_service,
    follow_service,
    notification_service,
    preference_service,
    song_service,
    update_service,
)

PASSWORD = "correct-horse-battery"
BODY = "A long enough announcement body for publishing."
ZERO = {"song": 0, "album": 0, "news": 0}


def make_user(number=1):
    return auth_service.register_user(f"fan{number}@example.com", f"fan_{number}", PASSWORD)


def make_artist(name):
    return artist_service.create_artist({"name": name})


def days_ago(n):
    return (utcnow().date() - timedelta(days=n)).isoformat()


def make_song(title, credits, days=None):
    data = {"title": title, "artists": [{"artist_id": a.id, "role": r} for a, r in credits]}
    if days is not None:
        data["release_date"] = days_ago(days)
    return song_service.create_song(data)


def add_album(artist, days, title="Debut EP"):
    return album_service.create_album(
        {"artist_id": artist.id, "title": title, "album_type": "ep", "release_date": days_ago(days)}
    )


def publish_news(artist, title="Big news"):
    update = update_service.create_update({"artist_id": artist.id, "title": title, "body": BODY})
    return update_service.publish_update(update)


def all_notifications():
    return db.session.scalars(sa.select(Notification).order_by(Notification.id)).all()


def recipients(kind):
    return sorted(
        db.session.scalars(sa.select(Notification.user_id).where(Notification.kind == kind))
    )


def test_a_new_release_notifies_the_people_who_follow(app):
    fan, tems = make_user(1), make_artist("Tems")
    follow_service.follow_artist(fan, "tems")
    song = make_song("Free Mind", [(tems, "primary")], days=3)

    created = notification_service.generate_notifications()

    assert created == {"song": 1, "album": 0, "news": 0}
    (n,) = all_notifications()
    assert (n.user_id, n.artist_id, n.kind, n.item_id, n.read_at) == (
        fan.id, tems.id, "song", song.id, None,
    )


def test_running_the_job_again_creates_nothing_new(app):
    fan, tems = make_user(1), make_artist("Tems")
    follow_service.follow_artist(fan, "tems")
    make_song("Free Mind", [(tems, "primary")], days=3)

    assert notification_service.generate_notifications() == {"song": 1, "album": 0, "news": 0}
    assert notification_service.generate_notifications() == ZERO
    assert len(all_notifications()) == 1


def test_things_that_were_there_before_you_followed_do_not_notify(app):
    fan, tems = make_user(1), make_artist("Tems")
    make_song("Already Out", [(tems, "primary")], days=3)
    publish_news(tems)
    follow_service.follow_artist(fan, "tems")

    assert notification_service.generate_notifications() == ZERO


def test_old_releases_never_notify_even_when_they_are_added_later(app):
    fan, tems = make_user(1), make_artist("Tems")
    follow_service.follow_artist(fan, "tems")
    make_song("Old Hit", [(tems, "primary")], days=30)  # like importing an old catalogue
    add_album(tems, 40, "Old Album")

    assert notification_service.generate_notifications() == ZERO


def test_news_notifies_followers(app):
    fan, tems = make_user(1), make_artist("Tems")
    follow_service.follow_artist(fan, "tems")
    update = publish_news(tems)

    assert notification_service.generate_notifications() == {"song": 0, "album": 0, "news": 1}
    (n,) = all_notifications()
    assert (n.user_id, n.kind, n.item_id) == (fan.id, "news", update.id)


def test_albums_notify_followers(app):
    fan, tems = make_user(1), make_artist("Tems")
    follow_service.follow_artist(fan, "tems")
    album = add_album(tems, 2)

    assert notification_service.generate_notifications() == {"song": 0, "album": 1, "news": 0}
    (n,) = all_notifications()
    assert (n.user_id, n.artist_id, n.kind, n.item_id) == (fan.id, tems.id, "album", album.id)


def test_collaborations_notify_each_follower_once(app):
    one, two = make_user(1), make_user(2)
    tems, asake = make_artist("Tems"), make_artist("Asake")
    follow_service.follow_artist(one, "tems")
    follow_service.follow_artist(one, "asake")
    follow_service.follow_artist(two, "asake")
    make_song("Collab", [(tems, "primary"), (asake, "featured")], days=1)

    created = notification_service.generate_notifications()

    assert created == {"song": 2, "album": 0, "news": 0}
    assert sorted((n.user_id, n.artist_id) for n in all_notifications()) == [
        (one.id, tems.id),
        (two.id, asake.id),
    ]


def test_per_artist_switches_and_preferences_are_respected(app):
    quiet, no_releases, no_news, everything = [make_user(n) for n in (1, 2, 3, 4)]
    tems = make_artist("Tems")
    follow_service.follow_artist(quiet, "tems", notify=False)
    for user in (no_releases, no_news, everything):
        follow_service.follow_artist(user, "tems")
    preference_service.update_preferences(no_releases, {"notify_releases": False})
    preference_service.update_preferences(no_news, {"notify_news": False})
    make_song("Free Mind", [(tems, "primary")], days=1)
    publish_news(tems)

    notification_service.generate_notifications()

    assert recipients("song") == sorted([no_news.id, everything.id])
    assert recipients("news") == sorted([no_releases.id, everything.id])


def test_disabled_accounts_are_skipped(app):
    active, disabled, tems = make_user(1), make_user(2), make_artist("Tems")
    follow_service.follow_artist(active, "tems")
    follow_service.follow_artist(disabled, "tems")
    disabled.is_active = False
    db.session.commit()
    make_song("Free Mind", [(tems, "primary")], days=1)

    assert notification_service.generate_notifications() == {"song": 1, "album": 0, "news": 0}
    assert recipients("song") == [active.id]


def test_archived_artists_do_not_notify(app):
    fan, tems = make_user(1), make_artist("Tems")
    follow_service.follow_artist(fan, "tems")
    make_song("Free Mind", [(tems, "primary")], days=1)
    add_album(tems, 1)
    publish_news(tems)
    artist_service.archive_artist(tems)

    assert notification_service.generate_notifications() == ZERO


def test_unpublished_and_hidden_items_do_not_notify(app):
    fan, tems = make_user(1), make_artist("Tems")
    follow_service.follow_artist(fan, "tems")
    update_service.create_update({"artist_id": tems.id, "title": "Just a draft", "body": BODY})
    song_service.archive_song(make_song("Hidden song", [(tems, "primary")], days=1))
    album_service.archive_album(add_album(tems, 1, "Hidden EP"))

    assert notification_service.generate_notifications() == ZERO


def test_listing_notifications_includes_details_and_counts(app):
    fan, tems = make_user(1), make_artist("Tems")
    follow_service.follow_artist(fan, "tems")
    song = make_song("Free Mind", [(tems, "primary")], days=2)
    publish_news(tems)
    notification_service.generate_notifications()

    items, total = notification_service.list_notifications(fan, 1, 10)

    assert total == 2
    assert {i["kind"] for i in items} == {"song", "news"}
    song_item = next(i for i in items if i["kind"] == "song")
    assert song_item["obj"].id == song.id
    assert song_item["artist"].name == "Tems"
    assert notification_service.unread_count(fan) == 2


def test_notifications_vanish_while_their_item_is_hidden(app):
    fan, tems = make_user(1), make_artist("Tems")
    follow_service.follow_artist(fan, "tems")
    song = make_song("Free Mind", [(tems, "primary")], days=1)
    notification_service.generate_notifications()
    assert notification_service.unread_count(fan) == 1

    song_service.archive_song(song)
    assert notification_service.list_notifications(fan, 1, 10) == ([], 0)
    assert notification_service.unread_count(fan) == 0

    song_service.restore_song(song)
    assert notification_service.unread_count(fan) == 1


def test_marking_notifications_as_read(app):
    fan, other, tems = make_user(1), make_user(2), make_artist("Tems")
    follow_service.follow_artist(fan, "tems")
    follow_service.follow_artist(other, "tems")
    make_song("Free Mind", [(tems, "primary")], days=1)
    publish_news(tems)
    notification_service.generate_notifications()

    items, _ = notification_service.list_notifications(fan, 1, 10)
    first = items[0]["notification"]
    assert notification_service.mark_read(fan, first.id).read_at is not None
    assert notification_service.unread_count(fan) == 1
    assert notification_service.list_notifications(fan, 1, 10, unread_only=True)[1] == 1

    with pytest.raises(NotFoundError):
        notification_service.mark_read(other, first.id)  # somebody else's notification
    with pytest.raises(NotFoundError):
        notification_service.mark_read(fan, 999999)

    assert notification_service.mark_all_read(fan) == 1
    assert notification_service.mark_all_read(fan) == 0
    assert notification_service.unread_count(other) == 2


def test_cleanup_removes_only_notifications_read_long_ago(app):
    fan, tems = make_user(1), make_artist("Tems")
    follow_service.follow_artist(fan, "tems")
    for title in ("One", "Two", "Three"):
        make_song(title, [(tems, "primary")], days=1)
    notification_service.generate_notifications()

    old, recent, unread = all_notifications()
    old.read_at = utcnow() - timedelta(days=100)
    recent.read_at = utcnow() - timedelta(days=5)
    db.session.commit()

    assert notification_service.cleanup_notifications() == 1
    assert sorted(n.id for n in all_notifications()) == sorted([recent.id, unread.id])