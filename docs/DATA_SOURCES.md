# Data sources

Last verified: 2026-11-18. Re-check terms before launch and before any monetization.

## MusicBrainz (in use)
- Access: public web service, no API key. https://musicbrainz.org/doc/MusicBrainz_API
- Rules: at most 1 request per second, and an identifying User-Agent with a contact.
- Licensing: core data (artists, releases, URL relationships) is CC0. Tags and ratings are CC BY-NC-SA, which we do NOT use.
- Commercial use of the web service requires a MetaBrainz plan. Decision needed before any monetization.
- What we import: MusicBrainz id, official links, albums/EPs/singles (no live/remix/compilation), and an inferred debut year. We never overwrite admin-edited values.

## Candidates for popularity metrics (decision pending, nothing built)
- Last.fm: non-commercial use only unless a commercial agreement is made.
- YouTube Data API: stored statistics must be refreshed or deleted within 30 days, which conflicts with long-term history.
- Community signals from our own users (follows, reactions): no external licensing.

## Not used
- Spotify: terms not verified yet. We do not scrape X, TikTok or Spotify.

## Decision log
- 2026-11-19: Platform is non-commercial for now, with monetization planned later. Non-commercial sources (MusicBrainz web service, Last.fm) are allowed during development. Before any monetization: get a MetaBrainz commercial plan (or replace the source) and a Last.fm commercial agreement (or drop it), then set `allows_commercial_use` accordingly.

## Last.fm (in use for audience numbers, non-commercial)
- Access: free API key, `artist.getInfo` by MusicBrainz id. We stay far below the roughly 5 requests per second guidance (1 per second).
- Terms: non-commercial use only unless a commercial agreement is made. Storage and attribution terms NOT yet verified (the terms page could not be read on 2026-11-19). Read https://www.last.fm/api/tos before launch.
- We store listener and play counts, once per artist per day, and credit Last.fm on the Radar.
- Flag: `data_sources.allows_commercial_use` is false. Do not flip it without a signed agreement.

## Decision log
- 2026-11-19: Platform is non-commercial for now, with monetization planned later. Before any monetization: get a MetaBrainz commercial plan (or replace the source) and a Last.fm commercial agreement (or drop it), then set `allows_commercial_use` accordingly.