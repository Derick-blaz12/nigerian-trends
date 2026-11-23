from datetime import timedelta

import pytest

from app.errors import ForbiddenError, NotFoundError, ValidationError
from app.extensions import db
from app.models import Comment, Reaction
from app.models.mixins import utcnow
from app.services import (
    artist_service,
    auth_service,
    genre_service,
    ranking_service,
    reaction_service,
    song_service,
)

PASSWORD = "correct-horse-battery"


def make_user(number):
    return auth_service.register_user(f"fan{number}@example.com", f"fan_{number}", PASSWORD)


def make_song(title="Free Mind", artist=None, **extra):
    artist = artist or artist_service.create_artist({"name": f"Artist for {title}"})
    return song_service.create_song(
        {"title": title, "artists": [{"artist_id": artist.id, "role": "primary"}], **extra}
    )


def react(users, song, kind, days_ago=0):
    for user in users:
        db.session.add(
            Reaction(
                user_id=user.id, song_id=song.id, kind=kind,
                created_at=utcnow() - timedelta(days=days_ago),
            )
        )
    db.session.commit()


def add_comment(user, song, body="Great one", **extra):
    comment = Comment(song_id=song.id, user_id=user.id, body=body, **extra)
    db.session.add(comment)
    db.session.commit()
    return comment


# ---------- reactions ----------

def test_reacting_is_idempotent(app):
    fan, song = make_user(1), make_song()

    assert reaction_service.set_reaction(fan, song.id, "like") is True
    assert reaction_service.set_reaction(fan, song.id, "like") is False
    assert reaction_service.song_stats(song.id)["likes"] == 1

    assert reaction_service.remove_reaction(fan, song.id, "like") is True
    assert reaction_service.remove_reaction(fan, song.id, "like") is False
    assert reaction_service.song_stats(song.id)["likes"] == 0


def test_like_and_recommend_are_independent(app):
    fan, song = make_user(1), make_song()
    reaction_service.set_reaction(fan, song.id, "like")
    reaction_service.set_reaction(fan, song.id, "recommend")

    stats = reaction_service.song_stats(song.id, viewer_id=fan.id)
    assert (stats["likes"], stats["recommends"]) == (1, 1)
    assert stats["me"] == {"liked": True, "recommended": True}

    reaction_service.remove_reaction(fan, song.id, "like")
    assert reaction_service.song_stats(song.id, viewer_id=fan.id)["me"] == {
        "liked": False, "recommended": True,
    }


def test_unknown_kinds_are_rejected(app):
    fan, song = make_user(1), make_song()
    with pytest.raises(ValidationError):
        reaction_service.set_reaction(fan, song.id, "love")
    with pytest.raises(ValidationError):
        reaction_service.remove_reaction(fan, song.id, "love")


def test_reactions_need_a_public_song(app):
    fan, song = make_user(1), make_song()
    song_service.archive_song(song)

    with pytest.raises(NotFoundError):
        reaction_service.set_reaction(fan, song.id, "like")
    with pytest.raises(NotFoundError):
        reaction_service.set_reaction(fan, 999999, "like")
    with pytest.raises(NotFoundError):
        reaction_service.song_stats(song.id)


def test_muted_users_cannot_react_but_can_take_a_reaction_back(app):
    fan, song = make_user(1), make_song()
    reaction_service.set_reaction(fan, song.id, "like")
    fan.muted_until = utcnow() + timedelta(days=1)
    db.session.commit()

    with pytest.raises(ForbiddenError):
        reaction_service.set_reaction(fan, song.id, "recommend")
    assert reaction_service.remove_reaction(fan, song.id, "like") is True


def test_disabled_accounts_do_not_count_in_song_stats(app):
    one, two, song = make_user(1), make_user(2), make_song()
    react([one, two], song, "like")
    two.is_active = False
    db.session.commit()

    assert reaction_service.song_stats(song.id)["likes"] == 1


# ---------- rankings ----------

def test_the_score_combines_likes_recommendations_and_commenters(app):
    one, two, three = make_user(1), make_user(2), make_user(3)
    song = make_song()
    react([one], song, "like")
    react([two], song, "recommend")
    add_comment(three, song)

    items, total = ranking_service.song_rankings("all_time", 10)

    assert total == 1
    item = items[0]
    assert item["song"].id == song.id
    assert (
        item["likes"], item["recommends"], item["commenters"], item["engaged_users"], item["score"]
    ) == (1, 1, 1, 3, 6)


def test_a_song_needs_enough_different_people_to_be_ranked(app):
    users = [make_user(n) for n in (1, 2, 3)]
    song = make_song()

    react(users[:2], song, "recommend")
    assert ranking_service.song_rankings("all_time", 10) == ([], 0)

    react(users[2:], song, "like")
    assert ranking_service.song_rankings("all_time", 10)[1] == 1


def test_one_person_cannot_inflate_a_song(app):
    one, two, three = make_user(1), make_user(2), make_user(3)
    song = make_song()
    for number in range(5):
        add_comment(one, song, f"comment {number}")
    react([two], song, "like")
    react([three], song, "recommend")

    item = ranking_service.song_rankings("all_time", 10)[0][0]

    assert item["commenters"] == 1
    assert item["score"] == 1 + 3 + 2


def test_trending_only_counts_recent_activity(app):
    users = [make_user(n) for n in (1, 2, 3)]
    old_song, new_song = make_song("Old One"), make_song("New One")
    react(users, old_song, "like", days_ago=10)
    react(users, new_song, "like")

    trending, _ = ranking_service.song_rankings("trending", 10)
    all_time, _ = ranking_service.song_rankings("all_time", 10)

    assert [item["song"].title for item in trending] == ["New One"]
    assert {item["song"].title for item in all_time} == {"Old One", "New One"}


def test_ranking_order_prefers_score_then_newer_releases(app):
    users = [make_user(n) for n in (1, 2, 3)]
    top = make_song("Top Song")
    old = make_song("Old Song", release_date="2020-01-01")
    new = make_song("New Song", release_date="2024-01-01")
    react(users, top, "recommend")
    react(users, old, "like")
    react(users, new, "like")

    items, _ = ranking_service.song_rankings("all_time", 10)

    assert [item["song"].title for item in items] == ["Top Song", "New Song", "Old Song"]


def test_disabled_accounts_and_hidden_comments_do_not_count_towards_rankings(app):
    users = [make_user(n) for n in (1, 2, 3)]
    song = make_song()
    react(users[:2], song, "like")
    add_comment(users[2], song, status="hidden")
    assert ranking_service.song_rankings("all_time", 10) == ([], 0)

    add_comment(users[2], song, "A visible one")
    assert ranking_service.song_rankings("all_time", 10)[1] == 1

    users[0].is_active = False
    db.session.commit()
    assert ranking_service.song_rankings("all_time", 10) == ([], 0)


def test_songs_of_archived_artists_are_not_ranked(app):
    users = [make_user(n) for n in (1, 2, 3)]
    artist = artist_service.create_artist({"name": "Gone Act"})
    song = make_song(artist=artist)
    react(users, song, "like")
    assert ranking_service.song_rankings("all_time", 10)[1] == 1

    artist_service.archive_artist(artist)
    assert ranking_service.song_rankings("all_time", 10) == ([], 0)


def test_genre_filter_and_limit(app):
    genre_service.create_genre("Afrobeats")
    genre_service.create_genre("Highlife")
    users = [make_user(n) for n in (1, 2, 3)]
    a = make_song("Afro Song", genres=["afrobeats"])
    b = make_song("High Song", genres=["highlife"])
    c = make_song("Extra Song", genres=["afrobeats"])
    react(users, a, "recommend")
    react(users, b, "like")
    react(users, c, "like")

    items, total = ranking_service.song_rankings("all_time", 1)
    assert total == 3
    assert [item["song"].title for item in items] == ["Afro Song"]

    afro, afro_total = ranking_service.song_rankings("all_time", 10, genre="afrobeats")
    assert [item["song"].title for item in afro] == ["Afro Song", "Extra Song"]
    assert afro_total == 2


def test_an_invalid_period_is_rejected(app):
    with pytest.raises(ValidationError):
        ranking_service.song_rankings("daily", 10)