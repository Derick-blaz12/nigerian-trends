from datetime import timedelta

import pytest

from app.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.extensions import db
from app.models import Comment, CommentReport
from app.models.mixins import utcnow
from app.services import artist_service, auth_service, comment_service, song_service

PASSWORD = "correct-horse-battery"


def make_user(number):
    return auth_service.register_user(f"fan{number}@example.com", f"fan_{number}", PASSWORD)


def make_song(title="Free Mind"):
    artist = artist_service.create_artist({"name": f"Artist for {title}"})
    return song_service.create_song(
        {"title": title, "artists": [{"artist_id": artist.id, "role": "primary"}]}
    )


def say(user, song, body="Great song", **extra):
    return comment_service.create_comment(user, song.id, {"body": body, **extra})


def test_posting_and_listing_a_comment(app):
    fan, song = make_user(1), make_song()

    comment = say(fan, song, "  Love this beat  ")

    assert (comment.body, comment.user_id, comment.parent_id) == ("Love this beat", fan.id, None)
    result = comment_service.list_comments(song.id, 1, 20)
    assert result["total"] == 1
    assert [t["comment"].id for t in result["threads"]] == [comment.id]
    assert result["authors"] == {fan.id: "fan_1"}


def test_replies_nest_one_level_only(app):
    one, two = make_user(1), make_user(2)
    song, other = make_song("One"), make_song("Two")
    top = say(one, song, "Main comment")
    reply = say(two, song, "A reply", parent_id=top.id)
    assert reply.parent_id == top.id

    with pytest.raises(ValidationError):
        say(one, song, "Reply to a reply", parent_id=reply.id)
    with pytest.raises(ValidationError):
        say(one, other, "Wrong song", parent_id=top.id)
    with pytest.raises(ValidationError):
        say(one, song, "Ghost", parent_id=999999)

    result = comment_service.list_comments(song.id, 1, 20)
    assert [r.id for r in result["threads"][0]["replies"]] == [reply.id]


def test_the_same_comment_cannot_be_posted_twice_in_a_row(app):
    fan, song = make_user(1), make_song()
    first = say(fan, song, "Amazing song!")

    with pytest.raises(ConflictError) as excinfo:
        say(fan, song, "  amazing   SONG! ")
    assert excinfo.value.code == "duplicate_comment"
    assert say(fan, song, "A different thought").id

    first.created_at = utcnow() - timedelta(minutes=11)
    db.session.commit()
    assert say(fan, song, "Amazing song!").id != first.id


def test_comments_need_a_public_song(app):
    fan, song = make_user(1), make_song()
    song_service.archive_song(song)

    with pytest.raises(NotFoundError):
        say(fan, song)
    with pytest.raises(NotFoundError):
        comment_service.list_comments(song.id, 1, 20)


def test_muted_users_cannot_comment(app):
    fan, song = make_user(1), make_song()
    fan.muted_until = utcnow() + timedelta(days=2)
    db.session.commit()

    with pytest.raises(ForbiddenError) as excinfo:
        say(fan, song)
    assert excinfo.value.code == "muted"


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"body": ""},
        {"body": "ok", "extra": 1},
        {"body": "ok", "parent_id": "1"},
        {"body": "ok", "parent_id": True},
        "not a dict",
    ],
)
def test_bad_comment_requests_are_rejected(app, data):
    fan, song = make_user(1), make_song()
    with pytest.raises(ValidationError):
        comment_service.create_comment(fan, song.id, data)


def test_authors_can_edit_their_comments(app):
    fan, song = make_user(1), make_song()
    comment = say(fan, song, "First draft")

    edited = comment_service.edit_comment(fan, comment.id, {"body": "  Second draft "})
    assert edited.body == "Second draft"
    assert edited.edited_at is not None

    untouched = say(fan, song, "Untouched")
    same = comment_service.edit_comment(fan, untouched.id, {"body": "Untouched"})
    assert same.edited_at is None


def test_editing_is_limited(app):
    one, two, song = make_user(1), make_user(2), make_song()
    comment = say(one, song, "Mine")

    with pytest.raises(ForbiddenError):
        comment_service.edit_comment(two, comment.id, {"body": "Hijack"})
    with pytest.raises(ValidationError):
        comment_service.edit_comment(one, comment.id, {"body": "ok", "extra": 1})
    with pytest.raises(NotFoundError):
        comment_service.edit_comment(one, 999999, {"body": "x"})

    comment.status = "hidden"
    db.session.commit()
    with pytest.raises(ConflictError):
        comment_service.edit_comment(one, comment.id, {"body": "Edited"})

    comment.status = "visible"
    comment.created_at = utcnow() - timedelta(hours=25)
    db.session.commit()
    with pytest.raises(ConflictError) as excinfo:
        comment_service.edit_comment(one, comment.id, {"body": "Edited"})
    assert excinfo.value.code == "edit_window_closed"

    comment_service.delete_comment(one, comment.id)
    with pytest.raises(NotFoundError):
        comment_service.edit_comment(one, comment.id, {"body": "Edited"})


def test_authors_can_delete_their_comments(app):
    one, two, song = make_user(1), make_user(2), make_song()
    comment = say(one, song, "Regret this")
    report = CommentReport(comment_id=comment.id, reporter_id=two.id, reason="spam")
    db.session.add(report)
    db.session.commit()

    with pytest.raises(ForbiddenError):
        comment_service.delete_comment(two, comment.id)
    comment_service.delete_comment(one, comment.id)

    deleted = db.session.get(Comment, comment.id)
    assert deleted.body == "" and deleted.deleted_at is not None
    assert db.session.get(CommentReport, report.id).status == "reviewed"
    assert comment_service.list_comments(song.id, 1, 20)["total"] == 0
    with pytest.raises(NotFoundError):
        comment_service.delete_comment(one, comment.id)


@pytest.mark.parametrize("state", ["deleted", "removed", "hidden"])
def test_a_comment_with_replies_leaves_a_placeholder(app, state):
    one, two, song = make_user(1), make_user(2), make_song()
    parent = say(one, song, "Parent")
    say(two, song, "Reply stays", parent_id=parent.id)

    if state == "deleted":
        comment_service.delete_comment(one, parent.id)
    else:
        parent.status = state
        db.session.commit()

    result = comment_service.list_comments(song.id, 1, 20)
    assert result["total"] == 1
    thread = result["threads"][0]
    assert thread["comment"].id == parent.id
    assert comment_service.comment_state(thread["comment"]) == state
    assert [r.body for r in thread["replies"]] == ["Reply stays"]


def test_hidden_replies_are_omitted(app):
    one, two, song = make_user(1), make_user(2), make_song()
    parent = say(one, song, "Parent")
    reply = say(two, song, "Reply", parent_id=parent.id)
    reply.status = "hidden"
    db.session.commit()

    result = comment_service.list_comments(song.id, 1, 20)

    assert result["threads"][0]["replies"] == []


def test_comments_are_listed_newest_first_with_replies_oldest_first(app):
    one, two, song = make_user(1), make_user(2), make_song()
    first = say(one, song, "First")
    say(one, song, "Second")
    say(one, song, "Third")
    say(two, song, "Reply two", parent_id=first.id)
    say(two, song, "Reply one?", parent_id=first.id)

    page1 = comment_service.list_comments(song.id, 1, 2)
    assert page1["total"] == 3
    assert [t["comment"].body for t in page1["threads"]] == ["Third", "Second"]

    page2 = comment_service.list_comments(song.id, 2, 2)
    assert [t["comment"].body for t in page2["threads"]] == ["First"]
    assert [r.body for r in page2["threads"][0]["replies"]] == ["Reply two", "Reply one?"]


def test_recent_discussions_span_public_songs(app):
    one, two = make_user(1), make_user(2)
    a, b, gone = make_song("A Song"), make_song("B Song"), make_song("Gone Song")
    say(one, a, "On A")
    say(two, b, "On B")
    say(one, gone, "On the gone song")
    hidden = say(two, a, "Hidden one")
    hidden.status = "hidden"
    db.session.commit()
    song_service.archive_song(gone)

    result = comment_service.recent_comments(1, 10)

    assert result["total"] == 2
    assert [(c.body, s.title) for c, s in result["items"]] == [
        ("On B", "B Song"),
        ("On A", "A Song"),
    ]