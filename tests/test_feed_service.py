from datetime import timedelta

from app.models.mixins import utcnow
from app.services import (
    album_service,
    artist_service,
    auth_service,
    feed_service,
    follow_service,
    song_service,
    update_service,
)

PASSWORD = "correct-horse-battery"


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
    update = update_service.create_update(
        {"artist_id": artist.id, "title": title, "body": "A long enough announcement body for publishing."}
    )
    return update_service.publish_update(update)


def test_the_feed_is_empty_when_you_follow_nobody(app):
    fan = make_user()
    make_song("Free Mind", [(make_artist("Tems"), "primary")], days=3)

    assert feed_service.feed_items(fan, 1, 10) == ([], 0)


def test_the_feed_mixes_news_songs_and_albums_newest_first(app):
    fan, tems = make_user(), make_artist("Tems")
    follow_service.follow_artist(fan, "tems")
    make_song("Free Mind", [(tems, "primary")], days=10)
    add_album(tems, 5)
    publish_news(tems, "Big news")

    items, total = feed_service.feed_items(fan, 1, 10)

    assert total == 3
    assert [(i["kind"], i["obj"].title) for i in items] == [
        ("news", "Big news"),
        ("album", "Debut EP"),
        ("song", "Free Mind"),
    ]
    assert all(i["artist"].name == "Tems" for i in items)


def test_a_song_by_two_followed_artists_appears_once_under_the_first_credit(app):
    fan, tems, asake = make_user(), make_artist("Tems"), make_artist("Asake")
    follow_service.follow_artist(fan, "tems")
    follow_service.follow_artist(fan, "asake")
    make_song("Collab", [(tems, "primary"), (asake, "featured")], days=2)

    items, total = feed_service.feed_items(fan, 1, 10)

    assert total == 1
    assert items[0]["artist"].name == "Tems"


def test_only_primary_and_featured_credits_reach_the_feed(app):
    fan, tems, other = make_user(), make_artist("Tems"), make_artist("Other Act")
    follow_service.follow_artist(fan, "tems")
    make_song("Produced", [(other, "primary"), (tems, "producer")], days=2)
    make_song("Featured", [(other, "primary"), (tems, "featured")], days=2)

    items, _ = feed_service.feed_items(fan, 1, 10)

    assert [i["obj"].title for i in items] == ["Featured"]
    assert items[0]["artist"].name == "Tems"


def test_future_and_undated_releases_stay_out(app):
    fan, tems = make_user(), make_artist("Tems")
    follow_service.follow_artist(fan, "tems")
    make_song("Future", [(tems, "primary")], days=-3)
    make_song("Undated", [(tems, "primary")])
    add_album(tems, -3)

    assert feed_service.feed_items(fan, 1, 10) == ([], 0)


def test_hidden_items_never_appear(app):
    fan, tems = make_user(), make_artist("Tems")
    follow_service.follow_artist(fan, "tems")
    song_service.archive_song(make_song("Archived", [(tems, "primary")], days=2))
    album_service.archive_album(add_album(tems, 2, "Archived EP"))
    update_service.create_update(
        {"artist_id": tems.id, "title": "Just a draft", "body": "A long enough body for the draft."}
    )
    assert feed_service.feed_items(fan, 1, 10) == ([], 0)

    make_song("Visible", [(tems, "primary")], days=1)
    publish_news(tems)
    assert feed_service.feed_items(fan, 1, 10)[1] == 2

    artist_service.archive_artist(tems)
    assert feed_service.feed_items(fan, 1, 10) == ([], 0)


def test_artists_you_do_not_follow_are_left_out(app):
    fan, tems, asake = make_user(), make_artist("Tems"), make_artist("Asake")
    follow_service.follow_artist(fan, "tems")
    make_song("Mine", [(tems, "primary")], days=1)
    make_song("Theirs", [(asake, "primary")], days=1)
    publish_news(asake)

    items, total = feed_service.feed_items(fan, 1, 10)

    assert total == 1
    assert [i["obj"].title for i in items] == ["Mine"]


def test_the_feed_is_paginated_with_a_total(app):
    fan, tems = make_user(), make_artist("Tems")
    follow_service.follow_artist(fan, "tems")
    for n in range(1, 6):
        make_song(f"Song {n}", [(tems, "primary")], days=n)

    page3, total = feed_service.feed_items(fan, 3, 2)
    page1, _ = feed_service.feed_items(fan, 1, 2)

    assert total == 5
    assert [i["obj"].title for i in page3] == ["Song 5"]
    assert [i["obj"].title for i in page1] == ["Song 1", "Song 2"]