from app.collectors.http import PoliteClient

MBID_A = "11111111-1111-4111-8111-111111111111"
MBID_B = "22222222-2222-4222-8222-222222222222"
MBID_C = "33333333-3333-4333-8333-333333333333"
MBID_D = "44444444-4444-4444-8444-444444444444"


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    """Plays back queued responses (or raises queued exceptions) and records every call."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(
            {"url": url, "params": params, "headers": headers, "timeout": timeout}
        )
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClock:
    """A clock whose sleep() moves time forward instantly."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def make_http(*responses, **kwargs):
    clock = FakeClock()
    session = FakeSession(*responses)
    http = PoliteClient(
        "TestApp/1.0 ( test@example.com )",
        session=session,
        clock=clock,
        sleep=clock.sleep,
        jitter=lambda: 0.0,
        **kwargs,
    )
    return http, session, clock


def hit(name, country="NG", mbid=MBID_A, score=100, **extra):
    data = {
        "mbid": mbid, "name": name, "country": country,
        "disambiguation": None, "begin_year": None, "score": score,
    }
    data.update(extra)
    return data

def single(title, year=None, release_date=None, mbid=MBID_B):
    return {"mbid": mbid, "title": title, "year": year, "release_date": release_date}

def group(title, album_type="album", year=None, release_date=None, mbid=MBID_B):
    return {
        "mbid": mbid, "title": title, "album_type": album_type,
        "year": year, "release_date": release_date,
    }


class FakeMusicBrainz:
    """Stands in for MusicBrainzClient so sync logic is tested without any network."""

    def __init__(self, hits=None, details=None, groups=None, singles=None, errors=None):
        self.hits = hits or {}
        self.details = details or {}
        self.groups = groups or {}
        self.singles = singles or {}
        self.errors = errors or {}
        self.requests_made = 0
        self.searched = []

    def search_artists(self, name, limit=10):
        self.requests_made += 1
        self.searched.append(name)
        if name in self.errors:
            raise self.errors[name]
        return self.hits.get(name, [])

    def get_artist(self, mbid):
        self.requests_made += 1
        if mbid in self.errors:
            raise self.errors[mbid]
        return self.details[mbid] if mbid in self.details else {"links": []}

    def browse_release_groups(self, mbid):
        self.requests_made += 1
        return self.groups.get(mbid, [])

    def browse_singles(self, mbid):
        self.requests_made += 1
        return self.singles.get(mbid, [])

class FakeLastFm:
    """Stands in for LastFmClient so the sync logic is tested without any network."""

    def __init__(self, stats=None, errors=None):
        self.stats = stats or {}
        self.errors = errors or {}
        self.requests_made = 0
        self.requested = []

    def get_artist_stats(self, mbid):
        self.requests_made += 1
        self.requested.append(mbid)
        if mbid in self.errors:
            raise self.errors[mbid]
        return self.stats.get(mbid)