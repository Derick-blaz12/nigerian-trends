from datetime import date


def _iso(value):
    return value.isoformat() if value else None


def serialize_artist_summary(artist, admin=False):
    data = {
        "id": artist.id,
        "name": artist.name,
        "slug": artist.slug,
        "image_url": artist.image_url,
        "origin_city": artist.origin_city,
        "genres": [
            {"name": g.name, "slug": g.slug} for g in sorted(artist.genres, key=lambda g: g.name)
        ],
    }
    if admin:
        data["archived_at"] = _iso(artist.archived_at)
    return data


def serialize_artist_detail(artist, admin=False):
    data = serialize_artist_summary(artist, admin)
    albums = sorted(artist.albums, key=lambda a: a.release_date or date.min, reverse=True)
    credits = sorted(
        artist.song_credits, key=lambda c: c.song.release_date or date.min, reverse=True
    )
    data.update(
        bio=artist.bio,
        debut_year=artist.debut_year,
        albums=[
            {
                "id": a.id,
                "title": a.title,
                "album_type": a.album_type,
                "release_date": _iso(a.release_date),
                "cover_url": a.cover_url,
            }
            for a in albums
        ],
        songs=[
            {
                "id": c.song.id,
                "title": c.song.title,
                "release_date": _iso(c.song.release_date),
                "role": c.role,
            }
            for c in credits
        ],
    )
    if admin:
        data["created_at"] = _iso(artist.created_at)
        data["updated_at"] = _iso(artist.updated_at)
    return data