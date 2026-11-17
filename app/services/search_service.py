from app.errors import ValidationError
from app.services import album_service, artist_service, song_service

MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 100


def search(q, limit, session=None):
    q = (q or "").strip()
    if not MIN_QUERY_LENGTH <= len(q) <= MAX_QUERY_LENGTH:
        raise ValidationError(
            "q is invalid.",
            details={"q": f"Enter between {MIN_QUERY_LENGTH} and {MAX_QUERY_LENGTH} characters."},
        )
    artists, artist_total = artist_service.list_artists(1, limit, q=q, session=session)
    songs, song_total = song_service.list_songs(1, limit, q=q, session=session)
    albums, album_total = album_service.search_albums(q, limit, session=session)
    return {
        "query": q,
        "artists": artists,
        "songs": songs,
        "albums": albums,
        "totals": {"artists": artist_total, "songs": song_total, "albums": album_total},
    }