from app.api.serializers import (
    serialize_album_summary,
    serialize_artist_summary,
    serialize_song_summary,
    serialize_update_summary,
)


def _iso(value):
    return value.isoformat() if value else None


def serialize_artist_brief(artist):
    return {
        "id": artist.id,
        "name": artist.name,
        "slug": artist.slug,
        "image_url": artist.image_url,
    }


def serialize_item(kind, obj):
    """A song, album or news story, in the same shape the rest of the API uses."""
    if kind == "song":
        return serialize_song_summary(obj)
    if kind == "album":
        return serialize_album_summary(obj)
    return serialize_update_summary(obj)


def serialize_feed_item(item):
    return {
        "kind": item["kind"],
        "at": _iso(item["at"]),
        "artist": serialize_artist_brief(item["artist"]),
        "item": serialize_item(item["kind"], item["obj"]),
    }


def serialize_followed_artist(follow, artist):
    data = serialize_artist_summary(artist)
    data["notify"] = bool(follow.notify)
    data["followed_at"] = _iso(follow.created_at)
    return data


def serialize_notification(item):
    notification = item["notification"]
    return {
        "id": notification.id,
        "kind": item["kind"],
        "created_at": _iso(notification.created_at),
        "read": notification.read_at is not None,
        "artist": serialize_artist_brief(item["artist"]),
        "item": serialize_item(item["kind"], item["obj"]),
    }