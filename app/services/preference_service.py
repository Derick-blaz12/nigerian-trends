from app.errors import ValidationError
from app.extensions import db
from app.models import NotificationPreference

FIELDS = ("notify_releases", "notify_news", "email_digest")
DEFAULTS = {"notify_releases": True, "notify_news": True, "email_digest": False}


def get_preferences(user, session=None):
    session = session or db.session
    pref = session.get(NotificationPreference, user.id)
    if pref is None:
        return dict(DEFAULTS)
    return {field: getattr(pref, field) for field in FIELDS}


def update_preferences(user, data, session=None):
    session = session or db.session
    if not isinstance(data, dict) or not data:
        raise ValidationError("Provide at least one setting to change.")
    unknown = [key for key in data if key not in FIELDS]
    if unknown:
        raise ValidationError("Unknown fields.", details={k: "Unknown field." for k in unknown})
    for key, value in data.items():
        if not isinstance(value, bool):
            raise ValidationError(f"{key} is invalid.", details={key: "Must be true or false."})

    pref = session.get(NotificationPreference, user.id)
    if pref is None:
        pref = NotificationPreference(user_id=user.id)
        session.add(pref)
    for key, value in data.items():
        setattr(pref, key, value)
    session.commit()
    return get_preferences(user, session)