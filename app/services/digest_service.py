from datetime import timedelta

from flask import current_app

from app.following.rules import DEFAULT_RULES
from app.models.mixins import utcnow
from app.services import notification_service

DIGEST_WINDOW_DAYS = 7


def _describe(item):
    artist, obj = item["artist"], item["obj"]
    if item["kind"] == "song":
        return f'{artist.name}: new song "{obj.title}"'
    if item["kind"] == "album":
        return f'{artist.name}: new {obj.album_type} "{obj.title}"'
    return f'{artist.name}: news "{obj.title}"'


def build_digest(user, session=None, rules=DEFAULT_RULES):
    """What an email digest would say, or None if there is nothing new.

    Nothing is sent: emails need a domain and a provider, which come in Phase 14.
    """
    since = utcnow() - timedelta(days=DIGEST_WINDOW_DAYS)
    items, total = notification_service.list_notifications(
        user, 1, rules.digest_max_items, unread_only=True, since=since, session=session
    )
    if total == 0 or not items:
        return None

    noun = "thing" if total == 1 else "things"
    subject = f"{total} new {noun} from artists you follow"
    site = current_app.config["SITE_URL"]
    lines = [f"- {_describe(item)}" for item in items]
    if total > len(items):
        lines.append(f"...and {total - len(items)} more")

    body = "\n".join(
        [
            f"Hi {user.username},",
            "",
            f"{subject}:",
            "",
            *lines,
            "",
            f"See everything: {site}/notifications",
            "",
            "You're getting this because you turned on email digests. "
            "You can change that any time in your notification settings.",
        ]
    )
    return {"subject": subject, "body": body, "count": total, "shown": len(items)}