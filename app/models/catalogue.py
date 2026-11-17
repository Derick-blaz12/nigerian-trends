from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.mixins import TimestampMixin

artist_genres = db.Table(
    "artist_genres",
    sa.Column("artist_id", sa.ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("genre_id", sa.ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True),
)

song_genres = db.Table(
    "song_genres",
    sa.Column("song_id", sa.ForeignKey("songs.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("genre_id", sa.ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True),
)


class Genre(db.Model):
    __tablename__ = "genres"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(60), unique=True)
    slug: Mapped[str] = mapped_column(sa.String(80), unique=True)


class Artist(TimestampMixin, db.Model):
    __tablename__ = "artists"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(200), index=True)
    slug: Mapped[str] = mapped_column(sa.String(220), unique=True)
    bio: Mapped[str | None] = mapped_column(sa.Text)
    image_url: Mapped[str | None] = mapped_column(sa.String(500))
    origin_city: Mapped[str | None] = mapped_column(sa.String(100))
    debut_year: Mapped[int | None]
    archived_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    genres: Mapped[list["Genre"]] = relationship(secondary=artist_genres)
    albums: Mapped[list["Album"]] = relationship(back_populates="artist")
    song_credits: Mapped[list["SongArtist"]] = relationship(back_populates="artist")


class Album(TimestampMixin, db.Model):
    __tablename__ = "albums"

    id: Mapped[int] = mapped_column(primary_key=True)
    artist_id: Mapped[int] = mapped_column(sa.ForeignKey("artists.id"), index=True)
    title: Mapped[str] = mapped_column(sa.String(200))
    album_type: Mapped[str] = mapped_column(
        sa.String(20), default="album", server_default="album"
    )
    release_date: Mapped[date | None] = mapped_column(sa.Date)
    cover_url: Mapped[str | None] = mapped_column(sa.String(500))

    artist: Mapped["Artist"] = relationship(back_populates="albums")
    songs: Mapped[list["Song"]] = relationship(back_populates="album")

    __table_args__ = (
        sa.UniqueConstraint("artist_id", "title", name="uq_albums_artist_title"),
        sa.CheckConstraint(
            "album_type IN ('album', 'ep', 'single', 'mixtape')", name="ck_albums_type"
        ),
    )


class Song(TimestampMixin, db.Model):
    __tablename__ = "songs"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(sa.String(200), index=True)
    album_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("albums.id", ondelete="SET NULL"), index=True
    )
    track_number: Mapped[int | None]
    release_date: Mapped[date | None] = mapped_column(sa.Date, index=True)
    duration_seconds: Mapped[int | None]
    isrc: Mapped[str | None] = mapped_column(sa.String(12), unique=True)

    album: Mapped["Album | None"] = relationship(back_populates="songs")
    credits: Mapped[list["SongArtist"]] = relationship(
        back_populates="song", cascade="all, delete-orphan", order_by="SongArtist.position"
    )
    genres: Mapped[list["Genre"]] = relationship(secondary=song_genres)


class SongArtist(db.Model):
    """Collaboration table: one row per artist per role on a song."""

    __tablename__ = "song_artists"

    song_id: Mapped[int] = mapped_column(
        sa.ForeignKey("songs.id", ondelete="CASCADE"), primary_key=True
    )
    artist_id: Mapped[int] = mapped_column(
        sa.ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(sa.String(20), primary_key=True, default="primary")
    position: Mapped[int] = mapped_column(default=0, server_default="0")

    song: Mapped["Song"] = relationship(back_populates="credits")
    artist: Mapped["Artist"] = relationship(back_populates="song_credits")

    __table_args__ = (
        sa.CheckConstraint(
            "role IN ('primary', 'featured', 'producer', 'writer')",
            name="ck_song_artists_role",
        ),
    )


class ExternalLink(TimestampMixin, db.Model):
    __tablename__ = "external_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    artist_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("artists.id", ondelete="CASCADE"), index=True
    )
    song_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("songs.id", ondelete="CASCADE"), index=True
    )
    album_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("albums.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(sa.String(40))
    url: Mapped[str] = mapped_column(sa.String(500))

    __table_args__ = (
        # Exactly one of the three targets must be set (PostgreSQL function).
        sa.CheckConstraint(
            "num_nonnulls(artist_id, song_id, album_id) = 1",
            name="ck_external_links_one_target",
        ),
        sa.UniqueConstraint("platform", "url", name="uq_external_links_platform_url"),
    )