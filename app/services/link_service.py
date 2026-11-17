import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.errors import ConflictError, NotFoundError, ValidationError
from app.extensions import db
from app.models import Album, Artist, ExternalLink, Song
from app.utils.catalogue import validate_link

TARGETS = {
    "artist": ("artist_id", Artist),
    "song": ("song_id", Song),
    "album": ("album_id", Album),
}
MAX_LINKS_PER_TARGET = 20


def list_links(target_type, target_id, session=None):
    session = session or db.session
    column = getattr(ExternalLink, TARGETS[target_type][0])
    return session.scalars(
        sa.select(ExternalLink)
        .where(column == target_id)
        .order_by(ExternalLink.platform, ExternalLink.id)
    ).all()


def add_link(target_type, target_id, data, session=None):
    session = session or db.session
    column_name, model = TARGETS[target_type]

    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object.")
    unknown = [k for k in data if k not in ("platform", "url")]
    if unknown:
        raise ValidationError("Unknown fields.", details={k: "Unknown field." for k in unknown})
    missing = [f for f in ("platform", "url") if data.get(f) in (None, "")]
    if missing:
        raise ValidationError(
            "Missing required fields.", details={f: "This field is required." for f in missing}
        )
    platform, url = validate_link(data["platform"], data["url"])

    if session.get(model, target_id) is None:
        raise NotFoundError(f"{target_type.capitalize()} not found.")

    existing = session.scalar(
        sa.select(sa.func.count())
        .select_from(ExternalLink)
        .where(getattr(ExternalLink, column_name) == target_id)
    )
    if existing >= MAX_LINKS_PER_TARGET:
        raise ValidationError(
            "Too many links.", details={"links": f"At most {MAX_LINKS_PER_TARGET} links per item."}
        )

    link = ExternalLink(platform=platform, url=url, **{column_name: target_id})
    session.add(link)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ConflictError("This link is already in use.", details={"url": "Already added."}) from None
    return link


def delete_link(link_id, session=None):
    session = session or db.session
    link = session.get(ExternalLink, link_id)
    if link is None:
        raise NotFoundError("Link not found.")
    session.delete(link)
    session.commit()