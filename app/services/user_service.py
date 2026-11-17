import sqlalchemy as sa

from app.extensions import db
from app.models import User


def list_users(page, per_page, session=None):
    session = session or db.session
    total = session.scalar(sa.select(sa.func.count()).select_from(User))
    items = session.scalars(
        sa.select(User).order_by(User.id).limit(per_page).offset((page - 1) * per_page)
    ).all()
    return items, total