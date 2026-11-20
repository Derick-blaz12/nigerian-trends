from app.collectors.http import CollectorError
from app.collectors.normalize import is_mbid

TEMPORARY_ERRORS = {11, 16, 29}


def _count(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


class LastFmClient:
    def __init__(self, http, api_key, base_url="https://ws.audioscrobbler.com/2.0/"):
        self.http = http
        self.api_key = api_key
        self.base_url = base_url

    @property
    def requests_made(self):
        return self.http.requests_made

    def get_artist_stats(self, mbid):
        """Returns {'listeners': int, 'playcount': int or None}, or None if there is no usable data."""
        if not is_mbid(mbid):
            raise CollectorError("Invalid MusicBrainz id.")
        data = self.http.get_json(
            self.base_url,
            {
                "method": "artist.getInfo",
                "mbid": mbid,
                "api_key": self.api_key,
                "format": "json",
                "autocorrect": 0,
            },
            accept_client_errors=True,
        )
        if not isinstance(data, dict):
            return None
        if "error" in data:
            code = data.get("error")
            if code == 6:  # the artist could not be found
                return None
            if code in TEMPORARY_ERRORS:
                raise CollectorError(f"Last.fm is temporarily unavailable (error {code}).")
            raise CollectorError(f"Last.fm error {code}: {data.get('message', '')}".strip())

        artist = data.get("artist")
        if not isinstance(artist, dict):
            return None
        returned = artist.get("mbid")
        if isinstance(returned, str) and returned and returned != mbid:
            return None  # not the artist we asked about, so we don't trust the numbers
        stats = artist.get("stats")
        if not isinstance(stats, dict):
            return None
        listeners = _count(stats.get("listeners"))
        if listeners is None:
            return None
        return {"listeners": listeners, "playcount": _count(stats.get("playcount", stats.get("plays")))}