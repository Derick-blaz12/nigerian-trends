# Nigerian Trends & Discovery Platform

A music discovery platform for emerging Nigerian artists: discover songs,
follow artists, see community rankings, and join discussions.

## Status
Phase 1 complete: project foundation.

## Requirements
- Python 3.11+

## Setup
    git clone <your-repo-url>
    cd nigerian-trends
    python -m venv venv
    source venv/bin/activate        # Windows: venv\Scripts\activate
    pip install -r requirements.txt
    cp .env.example .env            # then edit .env

## Run
    flask --app wsgi run --debug

## Test
    pytest

## Roadmap
15 phases, built milestone by milestone.

## Project layout
- `app/api` and `app/main`: Blueprints (HTTP only)
- `app/services`: business logic and database work
- `app/models`: SQLAlchemy models
- `app/utils`: validation and pagination helpers
- `app/errors.py`: error classes and JSON error handling
- `app/logging_config.py`: logging and request IDs

## Useful commands
    flask --app wsgi db upgrade        # apply migrations
    flask --app wsgi seed-genres       # insert starter genres
    pytest                             # run tests

    ## API overview
- `GET /api/v1/artists?q=&genre=&page=&per_page=`: list and search artists
- `GET /api/v1/artists/<slug>`: artist profile
- `/api/v1/admin/artists/...`: create, update, archive, restore, image upload (admin only)
- `GET /api/v1/songs?q=&genre=&artist=`, `GET /api/v1/songs/<id>`, `GET /api/v1/albums/<id>`
- `GET /api/v1/search?q=`: grouped search across artists, songs and albums
- `/api/v1/admin/songs|albums|links`: catalogue management (admin only)
- Pages: `/artists/<slug>`, `/songs/<id>`, `/search`
- `GET /api/v1/updates?artist=&category=&song=&album=`, `GET /api/v1/updates/<id>`: published news
- `/api/v1/admin/updates/...`: create, edit, publish, unpublish, archive, restore (admin only)
- Pages: `/news`, `/news/<id>`, `/admin/editorial` (dashboard)

## Next Up Radar
    flask --app wsgi collect-lastfm
    flask --app wsgi radar-show
    flask --app wsgi radar-explain --slug some-artist
    flask --app wsgi radar-set --slug some-artist --status pick --note "..." --days 30
Rules: `docs/RADAR.md`. Page: `/radar`. API: `/api/v1/radar`, `/api/v1/radar/rules`.
## Community
- `GET /api/v1/songs/<id>/community`, `PUT|DELETE /api/v1/songs/<id>/reactions/<like|recommend>`
- `GET|POST /api/v1/songs/<id>/comments`, `PATCH|DELETE /api/v1/comments/<id>`, `POST /api/v1/comments/<id>/report`
- `GET /api/v1/rankings/songs?period=trending|all_time`, `GET /api/v1/discussions/recent`
- Admin: `/api/v1/admin/moderation/...` (queue, remove, restore, dismiss, mute, unmute)
Rules: `docs/COMMUNITY.md`.

- Pages: `/login`, `/register`, `/charts`, `/discussions`, plus a community panel on `/songs/<id>`
- `GET /api/v1/auth/session` tells pages who is signed in (200 with null for anonymous visitors)