import pytest

from app.errors import ConflictError, NotFoundError, ValidationError
from app.extensions import db
from app.following.rules import FollowRules, rules_as_dict
from app.services import artist_service, auth_service, follow_service

PASSWORD = "correct-horse-battery"


def make_user(number):
    return auth_service.register_user(f"fan{number}@example.com", f"fan_{number}", PASSWORD)


def make_artist(name):
    return artist_service.create_artist({"name": name})


def test_following_is_idempotent(app):
    fan = make_user(1)
    make_artist("Tems")

    follow, changed = follow_service.follow_artist(fan, "tems")
    assert changed is True and follow.notify is True

    _, changed = follow_service.follow_artist(fan, "tems")
    assert changed is False
    assert follow_service.follow_status("tems", fan.id) == {
        "followers": 1,
        "me": {"following": True, "notify": True},
    }


def test_unfollowing(app):
    fan = make_user(1)
    make_artist("Tems")
    follow_service.follow_artist(fan, "tems")

    assert follow_service.unfollow_artist(fan, "tems") is True
    assert follow_service.unfollow_artist(fan, "tems") is False
    assert follow_service.follow_status("tems", fan.id) == {
        "followers": 0,
        "me": {"following": False, "notify": False},
    }


def test_notifications_per_artist_default_on_and_can_be_changed(app):
    fan, other = make_user(1), make_user(2)
    make_artist("Tems")

    follow, _ = follow_service.follow_artist(fan, "tems")
    assert follow.notify is True

    _, changed = follow_service.follow_artist(fan, "tems", notify=False)
    assert changed is True
    assert follow_service.follow_status("tems", fan.id)["me"] == {"following": True, "notify": False}
    _, changed = follow_service.follow_artist(fan, "tems", notify=False)
    assert changed is False
    _, changed = follow_service.follow_artist(fan, "tems")  # no choice given: leave it alone
    assert changed is False
    assert follow_service.follow_status("tems", fan.id)["me"]["notify"] is False

    follow, changed = follow_service.follow_artist(other, "tems", notify=False)
    assert (changed, follow.notify) == (True, False)


@pytest.mark.parametrize("notify", ["yes", 1, "false"])
def test_notify_must_be_true_or_false(app, notify):
    fan = make_user(1)
    make_artist("Tems")
    with pytest.raises(ValidationError):
        follow_service.follow_artist(fan, "tems", notify=notify)


def test_unknown_and_archived_artists_cannot_be_followed(app):
    fan, gone = make_user(1), make_artist("Gone Act")
    artist_service.archive_artist(gone)

    with pytest.raises(NotFoundError):
        follow_service.follow_artist(fan, "gone-act")
    with pytest.raises(NotFoundError):
        follow_service.follow_artist(fan, "nobody")
    with pytest.raises(NotFoundError):
        follow_service.follow_status("gone-act")


def test_unfollowing_works_for_archived_artists_but_not_unknown_ones(app):
    fan, tems = make_user(1), make_artist("Tems")
    follow_service.follow_artist(fan, "tems")
    artist_service.archive_artist(tems)

    assert follow_service.unfollow_artist(fan, "tems") is True
    with pytest.raises(NotFoundError):
        follow_service.unfollow_artist(fan, "nobody")


def test_the_follow_limit(app):
    fan = make_user(1)
    for name in ("Tems", "Asake", "Rema"):
        make_artist(name)
    rules = FollowRules(max_follows=2)

    follow_service.follow_artist(fan, "tems", rules=rules)
    follow_service.follow_artist(fan, "asake", rules=rules)
    with pytest.raises(ConflictError) as excinfo:
        follow_service.follow_artist(fan, "rema", rules=rules)
    assert excinfo.value.code == "follow_limit"

    follow_service.follow_artist(fan, "tems", rules=rules)  # already following: not blocked
    follow_service.unfollow_artist(fan, "tems")
    assert follow_service.follow_artist(fan, "rema", rules=rules)[1] is True


def test_follower_counts_ignore_disabled_accounts(app):
    users = [make_user(n) for n in (1, 2, 3)]
    make_artist("Tems")
    for user in users:
        follow_service.follow_artist(user, "tems")
    assert follow_service.follow_status("tems")["followers"] == 3

    users[0].is_active = False
    db.session.commit()

    assert follow_service.follow_status("tems") == {"followers": 2}


def test_the_following_list_is_newest_first_and_hides_archived_artists(app):
    fan = make_user(1)
    make_artist("Asake")
    burna = make_artist("Burna Boy")
    make_artist("Cuppy")
    for slug in ("asake", "burna-boy", "cuppy"):
        follow_service.follow_artist(fan, slug)
    artist_service.archive_artist(burna)

    rows, total = follow_service.list_following(fan, 1, 10)
    assert total == 2
    assert [artist.name for _, artist in rows] == ["Cuppy", "Asake"]
    assert rows[0][0].notify is True

    rows, total = follow_service.list_following(fan, 2, 1)
    assert total == 2
    assert [artist.name for _, artist in rows] == ["Asake"]


def test_the_follow_rules_are_plain_data():
    data = rules_as_dict()
    assert data["max_follows"] == 500
    assert data["notify_window_days"] == 14