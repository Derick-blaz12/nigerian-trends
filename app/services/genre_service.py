import sqlalchemy as sa

from app.errors import ConflictError, NotFoundError, ValidationError
from app.extensions import db
from app.models import Genre
from app.utils.validation import clean_string, slugify


def list_genres(page, per_page, session=None):
    session = session or db.session
    total = session.scalar(sa.select(sa.func.count()).select_from(Genre))
    items = session.scalars(
        sa.select(Genre).order_by(Genre.name).limit(per_page).offset((page - 1) * per_page)
    ).all()
    return items, total


def get_genre_by_slug(slug, session=None):
    session = session or db.session
    genre = session.scalar(sa.select(Genre).where(Genre.slug == slug))
    if genre is None:
        raise NotFoundError("Genre not found.")
    return genre


def create_genre(name, session=None):
    session = session or db.session
    name = clean_string(name, "name", min_len=2, max_len=60)
    slug = slugify(name)
    if not slug:
        raise ValidationError("name is invalid.", details={"name": "Must contain letters or numbers."})

    exists = session.scalar(
        sa.select(Genre).where(sa.or_(Genre.slug == slug, sa.func.lower(Genre.name) == name.lower()))
    )
    if exists:
        raise ConflictError("A genre with this name already exists.")

    genre = Genre(name=name, slug=slug)
    session.add(genre)
    session.commit()
    return genre

MAX_GENRES = 10


def load_genres(slugs, session=None):
    """Turn a list of genre slugs from a request into Genre objects."""
    session = session or db.session
    if (
        not isinstance(slugs, list)
        or len(slugs) > MAX_GENRES
        or not all(isinstance(s, str) for s in slugs)
    ):
        raise ValidationError(
            "genres is invalid.",
            details={"genres": f"Must be a list of up to {MAX_GENRES} genre slugs."},
        )
    wanted = list(dict.fromkeys(s.strip().lower() for s in slugs))
    if not wanted:
        return []
    found = {g.slug: g for g in session.scalars(sa.select(Genre).where(Genre.slug.in_(wanted)))}
    unknown = [s for s in wanted if s not in found]
    if unknown:
        raise ValidationError(
            "genres is invalid.", details={"genres": "Unknown genres: " + ", ".join(unknown)}
        )
    return [found[s] for s in wanted]