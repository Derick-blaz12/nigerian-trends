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