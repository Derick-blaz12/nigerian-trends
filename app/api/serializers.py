from datetime import date


def _iso(value):
    return value.isoformat() if value else None


def _genres(items):
    return [{"name": g.name, "slug": g.slug} for g in sorted(items, key=lambda g: g.name)]


def _credits(song, admin=False):
    """Public pages never show archived artists; admins see every credit."""
    ordered = sorted(song.credits, key=lambda c: c.position)
    return [
        {"id": c.artist.id, "name": c.artist.name, "slug": c.artist.slug, "role": c.role}
        for c in ordered
        if admin or c.artist.archived_at is None
    ]


def serialize_link(link):
    return {"id": link.id, "platform": link.platform, "url": link.url}


# ---------- artists ----------

def serialize_artist_summary(artist, admin=False):
    data = {
        "id": artist.id,
        "name": artist.name,
        "slug": artist.slug,
        "image_url": artist.image_url,
        "origin_city": artist.origin_city,
        "genres": _genres(artist.genres),
    }
    if admin:
        data["archived_at"] = _iso(artist.archived_at)
    return data


def serialize_artist_detail(artist, admin=False, links=None):
    data = serialize_artist_summary(artist, admin)

    albums = [a for a in artist.albums if admin or a.archived_at is None]
    albums.sort(key=lambda a: a.release_date or date.min, reverse=True)
    credits = [c for c in artist.song_credits if admin or c.song.is_public]
    credits.sort(key=lambda c: c.song.release_date or date.min, reverse=True)

    album_items = []
    for album in albums:
        item = {
            "id": album.id,
            "title": album.title,
            "album_type": album.album_type,
            "release_date": _iso(album.release_date),
            "cover_url": album.cover_url,
        }
        if admin:
            item["archived_at"] = _iso(album.archived_at)
        album_items.append(item)

    song_items = []
    for credit in credits:
        item = {
            "id": credit.song.id,
            "title": credit.song.title,
            "release_date": _iso(credit.song.release_date),
            "role": credit.role,
        }
        if admin:
            item["archived_at"] = _iso(credit.song.archived_at)
        song_items.append(item)

    data.update(
        bio=artist.bio,
        debut_year=artist.debut_year,
        albums=album_items,
        songs=song_items,
        links=[serialize_link(link) for link in (links or [])],
    )
    if admin:
        data["created_at"] = _iso(artist.created_at)
        data["updated_at"] = _iso(artist.updated_at)
    return data


# ---------- songs ----------

def serialize_song_summary(song, admin=False):
    album = song.album
    data = {
        "id": song.id,
        "title": song.title,
        "release_date": _iso(song.release_date),
        "duration_seconds": song.duration_seconds,
        "artists": _credits(song, admin),
        "genres": _genres(song.genres),
        "album": (
            {"id": album.id, "title": album.title}
            if album is not None and (admin or album.archived_at is None)
            else None
        ),
    }
    if admin:
        data["archived_at"] = _iso(song.archived_at)
    return data


def serialize_song_detail(song, admin=False, links=None):
    data = serialize_song_summary(song, admin)
    data.update(
        track_number=song.track_number,
        isrc=song.isrc,
        links=[serialize_link(link) for link in (links or [])],
    )
    if admin:
        data["created_at"] = _iso(song.created_at)
        data["updated_at"] = _iso(song.updated_at)
    return data


# ---------- albums ----------

def serialize_album_summary(album, admin=False):
    data = {
        "id": album.id,
        "title": album.title,
        "album_type": album.album_type,
        "release_date": _iso(album.release_date),
        "cover_url": album.cover_url,
        "artist": {"id": album.artist.id, "name": album.artist.name, "slug": album.artist.slug},
    }
    if admin:
        data["archived_at"] = _iso(album.archived_at)
    return data


def serialize_album_detail(album, admin=False, links=None):
    data = serialize_album_summary(album, admin)
    songs = [s for s in album.songs if admin or s.is_public]
    songs.sort(key=lambda s: (s.track_number is None, s.track_number or 0, s.title.lower()))

    tracks = []
    for song in songs:
        item = {
            "id": song.id,
            "title": song.title,
            "track_number": song.track_number,
            "duration_seconds": song.duration_seconds,
            "artists": _credits(song, admin),
        }
        if admin:
            item["archived_at"] = _iso(song.archived_at)
        tracks.append(item)

    data.update(tracks=tracks, links=[serialize_link(link) for link in (links or [])])
    if admin:
        data["created_at"] = _iso(album.created_at)
        data["updated_at"] = _iso(album.updated_at)
    return data