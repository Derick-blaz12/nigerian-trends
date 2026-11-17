import re

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from app.errors import AuthenticationError, ConflictError, ForbiddenError, ValidationError
from app.extensions import db
from app.models import User
from app.models.mixins import utcnow
from app.utils.validation import is_valid_email

USERNAME_RE = re.compile(r"[a-z0-9_]{3,30}")
RESERVED_USERNAMES = {
    "admin", "administrator", "moderator", "mod", "support", "staff", "root",
    "system", "nextupradar", "nigeriantrends",
}
COMMON_PASSWORDS = {
    "password", "password1", "password123", "12345678", "123456789", "1234567890",
    "qwertyuiop", "iloveyou", "11111111", "abcd1234", "admin123", "welcome1",
    "letmein123", "passw0rd",
}
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128  # also stops huge inputs being hashed

INVALID_LOGIN_MESSAGE = "Invalid email/username or password."

# Hashed once at startup. Checking against it when the account doesn't
# exist keeps login timing similar for real and unknown accounts.
_DUMMY_HASH = generate_password_hash("not-a-real-password")


def normalize_email(email):
    if not isinstance(email, str):
        raise ValidationError("email is invalid.", details={"email": "Must be text."})
    email = email.strip().lower()
    if len(email) > 255 or not is_valid_email(email):
        raise ValidationError("email is invalid.", details={"email": "Enter a valid email address."})
    return email


def normalize_username(username):
    if not isinstance(username, str):
        raise ValidationError("username is invalid.", details={"username": "Must be text."})
    username = username.strip().lower()
    if not USERNAME_RE.fullmatch(username):
        raise ValidationError(
            "username is invalid.",
            details={"username": "Use 3-30 letters, numbers or underscores."},
        )
    if username in RESERVED_USERNAMES:
        raise ValidationError("username is invalid.", details={"username": "This username is reserved."})
    return username


def validate_password(password, email, username):
    if not isinstance(password, str):
        raise ValidationError("password is invalid.", details={"password": "Must be text."})
    if not (MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH):
        raise ValidationError(
            "password is invalid.",
            details={"password": f"Must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters."},
        )
    lowered = password.lower()
    if lowered in COMMON_PASSWORDS:
        raise ValidationError("password is invalid.", details={"password": "This password is too common."})
    if lowered in {email, username, email.split("@")[0]}:
        raise ValidationError(
            "password is invalid.", details={"password": "Must not be your email or username."}
        )


def register_user(email, username, password, session=None):
    """Create a regular user. Roles are never accepted from callers."""
    session = session or db.session
    email = normalize_email(email)
    username = normalize_username(username)
    validate_password(password, email, username)

    rows = session.scalars(
        sa.select(User).where(sa.or_(User.email == email, User.username == username))
    ).all()
    details = {}
    for row in rows:
        if row.email == email:
            details["email"] = "Already registered."
        if row.username == username:
            details["username"] = "Already taken."
    if details:
        raise ConflictError("An account with these details already exists.", details=details)

    user = User(email=email, username=username, role="user")
    user.set_password(password)
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        # Two people registering the same name at the same instant.
        session.rollback()
        raise ConflictError("An account with these details already exists.") from None
    return user


def authenticate(identifier, password, session=None):
    """Return the user for valid credentials, or raise."""
    session = session or db.session
    if (
        not isinstance(identifier, str)
        or not isinstance(password, str)
        or len(identifier) > 255
        or len(password) > MAX_PASSWORD_LENGTH
    ):
        raise AuthenticationError(INVALID_LOGIN_MESSAGE, code="invalid_credentials")

    identifier = identifier.strip().lower()
    user = session.scalar(
        sa.select(User).where(sa.or_(User.email == identifier, User.username == identifier))
    )
    password_ok = check_password_hash(user.password_hash if user else _DUMMY_HASH, password)
    if user is None or not password_ok:
        raise AuthenticationError(INVALID_LOGIN_MESSAGE, code="invalid_credentials")
    if not user.is_active:
        raise ForbiddenError("This account has been disabled.", code="account_disabled")

    user.last_login_at = utcnow()
    session.commit()
    return user