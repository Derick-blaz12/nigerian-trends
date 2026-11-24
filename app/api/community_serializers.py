from app.services.comment_service import comment_state

PLACEHOLDERS = {
    "deleted": "This comment was deleted.",
    "removed": "This comment was removed by a moderator.",
    "hidden": "This comment is hidden while it is reviewed.",
}


def _iso(value):
    return value.isoformat() if value else None


def serialize_comment(comment, authors, admin=False, replies=None):
    """Public readers never see the text or author of a deleted, hidden or removed comment."""
    state = comment_state(comment)
    shown = state == "visible" or admin
    data = {
        "id": comment.id,
        "song_id": comment.song_id,
        "parent_id": comment.parent_id,
        "state": state,
        "body": comment.body if shown else None,
        "placeholder": None if state == "visible" else PLACEHOLDERS[state],
        "author": (
            {"id": comment.user_id, "username": authors.get(comment.user_id)} if shown else None
        ),
        "created_at": _iso(comment.created_at),
        "edited_at": _iso(comment.edited_at),
    }
    if replies is not None:
        data["replies"] = [serialize_comment(reply, authors) for reply in replies]
    return data


def serialize_queue_item(item):
    comment, author = item["comment"], item["author"]
    return {
        "comment": {
            "id": comment.id,
            "body": comment.body,
            "status": comment.status,
            "song_id": comment.song_id,
            "song_title": item["song_title"],
            "created_at": _iso(comment.created_at),
            "edited_at": _iso(comment.edited_at),
        },
        "author": {
            "id": author.id,
            "username": author.username,
            "muted_until": _iso(author.muted_until),
        },
        "report_count": item["report_count"],
        "reports": [
            {
                "id": report.id,
                "reason": report.reason,
                "reporter": username,
                "created_at": _iso(report.created_at),
            }
            for report, username in item["reports"]
        ],
    }