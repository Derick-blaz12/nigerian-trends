from functools import wraps

from flask_login import current_user

from app.errors import AuthenticationError, ForbiddenError
from app.extensions import db, login_manager
from app.models import User


@login_manager.user_loader
def load_user(user_id):
    """Runs on every request that carries a session cookie."""
    try:
        user = db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None
    # A disabled account loses its session immediately.
    return user if user is not None and user.is_active else None


@login_manager.unauthorized_handler
def handle_unauthorized():
    raise AuthenticationError("Authentication required.")


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            raise AuthenticationError("Authentication required.")
        if not current_user.is_admin:
            raise ForbiddenError("Administrator access required.")
        return view(*args, **kwargs)

    return wrapper