# Next Up Radar: how it works

Rules version: see `app/radar/rules.py` (`RULES_VERSION`). Public copy: `GET /api/v1/radar/rules`.

## Who is eligible
Not archived, has public releases, not an editor's exclusion, at most 300,000 Last.fm listeners (when known), debuted at most 5 years ago (when known), and a release or news story in the last 2 years. Editor's picks skip these checks, except archiving.

## Points (an artist needs 10 to appear; picks always appear)
Audience growth up to 40, new release up to 25, news coverage 10, new career up to 10, editor's pick 30.

## Tuning
Every threshold is a starting guess. Change `app/radar/rules.py`, bump `RULES_VERSION`, run `flask --app wsgi radar-show`, and update the tests. Phase 15 tunes them against real user behaviour.

## Switching to commercial
Set `PLATFORM_COMMERCIAL=true`. Only sources with `allows_commercial_use = true` then feed the Radar. Before that, secure commercial licences (see `docs/DATA_SOURCES.md`).