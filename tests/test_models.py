import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Artist, ExternalLink, Reaction, Song, SongArtist, User


def make_user(n=1):
    return User(email=f"u{n}@example.com", username=f"user{n}", password_hash="x")


def test_duplicate_email_rejected(app):
    db.session.add(make_user(1))
    db.session.add(User(email="u1@example.com", username="other", password_hash="x"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_song_with_multiple_artists(app):
    a, b = Artist(name="A", slug="a"), Artist(name="B", slug="b")
    song = Song(title="Collab")
    song.credits = [
        SongArtist(artist=a, role="primary", position=0),
        SongArtist(artist=b, role="featured", position=1),
    ]
    db.session.add(song)
    db.session.commit()

    assert [c.artist.name for c in song.credits] == ["A", "B"]
    assert len(a.song_credits) == 1


def test_duplicate_reaction_rejected(app):
    user, song = make_user(), Song(title="T")
    db.session.add_all([user, song])
    db.session.commit()

    db.session.add(Reaction(user_id=user.id, song_id=song.id, kind="like"))
    db.session.commit()
    db.session.add(Reaction(user_id=user.id, song_id=song.id, kind="like"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_external_link_needs_exactly_one_target(app):
    db.session.add(ExternalLink(platform="youtube", url="https://youtube.com/x"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()