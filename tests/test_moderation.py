from datetime import timedelta

import pytest
import sqlalchemy as sa

from app.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.extensions import db
from app.models import Comment, CommentReport
from app.models.mixins import utcnow
from app.services import (
    artist_service,
    auth_service,
    comment_service,
    moderation_service,
    song_service,
)

PASSWORD = "correct-horse-battery"


def make_user(number):
    return auth_service.register_user(f"fan{number}@example.com", f"fan_{number}", PASSWORD)


def make_admin(number):
    user = make_user(number)
    user.role = "admin"
    db.session.commit()
    return user


def make_song(title="Free Mind"):
    artist = artist_service.create_artist({"name": f"Artist for {title}"})
    return song_service.create_song(
        {"title": title, "artists": [{"artist_id": artist.id, "role": "primary"}]}
    )


def say(user, song, body="Great song", **extra):
    return comment_service.create_comment(user, song.id, {"body": body, **extra})


def hide_with_reports(song, author, reporters):
    comment = say(author, song, "Borderline")
    for reporter in reporters:
        moderation_service.report_comment(reporter, comment.id, "abuse")
    return comment


def test_reporting_a_comment(app):
    author, reporter, song = make_user(1), make_user(2), make_song()
    comment = say(author, song, "Rude words")

    report = moderation_service.report_comment(reporter, comment.id, "abuse", "Insults another fan")
    assert report.reason == "abuse: Insults another fan"
    assert moderation_service.report_comment(make_user(3), comment.id, "spam").reason == "spam"

    with pytest.raises(ConflictError) as excinfo:
        moderation_service.report_comment(reporter, comment.id, "abuse")
    assert excinfo.value.code == "already_reported"


def test_reports_are_validated(app):
    author, reporter, song = make_user(1), make_user(2), make_song()
    comment = say(author, song, "Fine comment")

    with pytest.raises(ValidationError):
        moderation_service.report_comment(author, comment.id, "spam")  # your own comment
    with pytest.raises(ValidationError):
        moderation_service.report_comment(reporter, comment.id, "boring")
    with pytest.raises(ValidationError):
        moderation_service.report_comment(reporter, comment.id, "spam", "d" * 401)
    with pytest.raises(NotFoundError):
        moderation_service.report_comment(reporter, 999999, "spam")

    reporter.muted_until = utcnow() + timedelta(days=1)
    db.session.commit()
    with pytest.raises(ForbiddenError):
        moderation_service.report_comment(reporter, comment.id, "spam")

    reporter.muted_until = None
    db.session.commit()
    comment_service.delete_comment(author, comment.id)
    with pytest.raises(NotFoundError):
        moderation_service.report_comment(reporter, comment.id, "spam")


def test_three_reports_hide_a_comment_for_review(app):
    author, song = make_user(1), make_song()
    reporters = [make_user(n) for n in (2, 3, 4)]
    comment = say(author, song, "Borderline")

    for reporter in reporters[:2]:
        moderation_service.report_comment(reporter, comment.id, "abuse")
    assert db.session.get(Comment, comment.id).status == "visible"

    moderation_service.report_comment(reporters[2], comment.id, "abuse")
    hidden = db.session.get(Comment, comment.id)
    assert hidden.status == "hidden"
    assert "automatically" in hidden.moderation_note
    assert comment_service.list_comments(song.id, 1, 20)["total"] == 0


def test_the_queue_lists_commented_with_open_reports_most_reported_first(app):
    author, song, admin = make_user(1), make_song(), make_admin(9)
    first = say(author, song, "First problem")
    second = say(author, song, "Second problem")
    one, two = make_user(3), make_user(4)
    moderation_service.report_comment(one, first.id, "spam")
    moderation_service.report_comment(one, second.id, "abuse")
    moderation_service.report_comment(two, second.id, "hate")

    items, total = moderation_service.report_queue(1, 10)

    assert total == 2
    assert [item["comment"].id for item in items] == [second.id, first.id]
    assert items[0]["report_count"] == 2
    assert sorted(report.reason for report, _ in items[0]["reports"]) == ["abuse", "hate"]
    assert items[0]["author"].username == "fan_1"
    assert items[0]["song_title"] == "Free Mind"

    moderation_service.dismiss_reports(admin, second.id)
    assert moderation_service.report_queue(1, 10)[1] == 1


def test_removing_a_comment(app):
    author, reporter, song, admin = make_user(1), make_user(2), make_song(), make_admin(9)
    comment = say(author, song, "Bad stuff")
    moderation_service.report_comment(reporter, comment.id, "abuse")

    removed = moderation_service.remove_comment(admin, comment.id, note="Harassment")

    assert (removed.status, removed.moderated_by, removed.moderation_note) == (
        "removed", admin.id, "Harassment",
    )
    report = db.session.scalar(sa.select(CommentReport))
    assert (report.status, report.resolved_by) == ("reviewed", admin.id)
    assert comment_service.comment_state(removed) == "removed"

    with pytest.raises(ConflictError):
        moderation_service.remove_comment(admin, comment.id)
    other = say(author, song, "Another")
    comment_service.delete_comment(author, other.id)
    with pytest.raises(ConflictError):
        moderation_service.remove_comment(admin, other.id)
    with pytest.raises(NotFoundError):
        moderation_service.remove_comment(admin, 999999)


def test_dismissing_reports_restores_an_auto_hidden_comment(app):
    author, song, admin = make_user(1), make_song(), make_admin(9)
    comment = hide_with_reports(song, author, [make_user(n) for n in (2, 3, 4)])
    assert db.session.get(Comment, comment.id).status == "hidden"

    dismissed = moderation_service.dismiss_reports(admin, comment.id)

    assert dismissed.status == "visible"
    assert {r.status for r in db.session.scalars(sa.select(CommentReport))} == {"dismissed"}
    assert comment_service.list_comments(song.id, 1, 20)["total"] == 1

    gone = say(author, song, "Gone")
    moderation_service.remove_comment(admin, gone.id)
    with pytest.raises(ConflictError):
        moderation_service.dismiss_reports(admin, gone.id)


def test_restoring_a_removed_comment(app):
    author, song, admin = make_user(1), make_song(), make_admin(9)
    comment = say(author, song, "Removed by mistake")
    moderation_service.remove_comment(admin, comment.id)

    restored = moderation_service.restore_comment(admin, comment.id)

    assert restored.status == "visible"
    with pytest.raises(ConflictError):
        moderation_service.restore_comment(admin, comment.id)


def test_muting_and_unmuting(app):
    fan, admin, other_admin = make_user(1), make_admin(2), make_admin(3)

    muted = moderation_service.mute_user(admin, fan.id, 7)
    assert muted.is_muted
    remaining = muted.muted_until - utcnow()
    assert timedelta(days=6, hours=23) < remaining <= timedelta(days=7)

    with pytest.raises(ConflictError):
        moderation_service.mute_user(admin, other_admin.id, 7)
    with pytest.raises(NotFoundError):
        moderation_service.mute_user(admin, 999999, 7)
    assert moderation_service.unmute_user(fan.id).is_muted is False


@pytest.mark.parametrize("days", [0, 366, "7"])
def test_mute_length_is_validated(app, days):
    fan, admin = make_user(1), make_admin(2)
    with pytest.raises(ValidationError):
        moderation_service.mute_user(admin, fan.id, days)


def test_a_muted_user_cannot_comment_until_unmuted(app):
    fan, admin, song = make_user(1), make_admin(2), make_song()
    moderation_service.mute_user(admin, fan.id, 1)

    with pytest.raises(ForbiddenError):
        say(fan, song)

    moderation_service.unmute_user(fan.id)
    assert say(fan, song).id