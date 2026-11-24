# Community: how it works

Rules version: `app/community/rules.py`. Public copy: `GET /api/v1/community/rules`.

## Popularity (community only)
Score = likes x 1 + recommendations x 3 + people who commented x 2. A song is ranked once at least 3 different people have engaged. `trending` counts the last 7 days, `all_time` counts everything. Disabled accounts, hidden, removed and deleted comments do not count.

Community popularity is never combined with external numbers (Last.fm, streaming). Every ranking response says `source: community`.

## Comments
Plain text, up to 2000 characters, at most 2 links, replies one level deep. Authors may edit for 24 hours. Deleting erases the text. Identical text from the same person within 10 minutes is rejected.

## Moderation
Anyone signed in can report a comment (one report each). Three open reports hide it for review. Admins can remove, restore, or dismiss reports, and mute a user for 1 to 365 days. Muted users can't comment, react or report.

## Known limits
Only the admin role exists. Auto-hide can be abused by a group of accounts, so admins should review the queue. Needs community guidelines, a privacy policy and terms before real users arrive.