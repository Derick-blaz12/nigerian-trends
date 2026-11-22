from app.errors import ForbiddenError


def ensure_can_post(user):
    """Muted users can't comment, react or report until the mute ends."""
    if user.is_muted:
        raise ForbiddenError(
            f"You are muted until {user.muted_until:%Y-%m-%d %H:%M} UTC.", code="muted"
        )