from app.collectors.http import CollectorError
from app.collectors.normalize import (
    is_mbid,
    normalize_artist_detail,
    normalize_artist_hit,
    normalize_release_group,
    normalize_single,
)


class MusicBrainzClient:
    """Thin wrapper over the MusicBrainz web service. It returns clean dicts, never raw JSON."""

    def __init__(self, http, base_url="https://musicbrainz.org/ws/2"):
        self.http = http
        self.base_url = base_url.rstrip("/")

    @property
    def requests_made(self):
        return self.http.requests_made

    def search_artists(self, name, limit=10):
        escaped = name.replace("\\", "\\\\").replace('"', '\\"')
        data = self.http.get_json(
            f"{self.base_url}/artist",
            {"query": f'artist:"{escaped}"', "limit": limit, "fmt": "json"},
        )
        hits = (data or {}).get("artists") or []
        return [hit for hit in (normalize_artist_hit(raw) for raw in hits) if hit]

    def get_artist(self, mbid):
        """Returns {'links': [...]}, or None if MusicBrainz no longer has this id."""
        if not is_mbid(mbid):
            raise CollectorError("Invalid MusicBrainz id.")
        data = self.http.get_json(
            f"{self.base_url}/artist/{mbid}", {"inc": "url-rels", "fmt": "json"}
        )
        return None if data is None else normalize_artist_detail(data)

    def _browse(self, mbid, kinds, normalize, max_pages):
        if not is_mbid(mbid):
            raise CollectorError("Invalid MusicBrainz id.")
        found, offset = [], 0
        for _ in range(max_pages):
            data = self.http.get_json(
                f"{self.base_url}/release-group",
                {"artist": mbid, "type": kinds, "limit": 100, "offset": offset, "fmt": "json"},
            )
            if data is None:
                break
            raw = data.get("release-groups") or []
            found.extend(item for item in (normalize(r) for r in raw) if item)
            offset += len(raw)
            if not raw or offset >= (data.get("release-group-count") or 0):
                break
        return found

    def browse_release_groups(self, mbid, max_pages=5):
        """Albums and EPs."""
        return self._browse(mbid, "album|ep", normalize_release_group, max_pages)

    def browse_singles(self, mbid, max_pages=5):
        """Plain singles, which we import as songs."""
        return self._browse(mbid, "single", normalize_single, max_pages)