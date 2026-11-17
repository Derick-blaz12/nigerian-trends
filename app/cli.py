import click

from app.errors import AppError, ConflictError
from app.extensions import db
from app.services import auth_service, genre_service

STARTER_GENRES = [
    "Afrobeats", "Afropop", "Afro-fusion", "Amapiano", "Alté", "Highlife",
    "Fuji", "Juju", "Apala", "Hip-hop", "Afro-soul", "R&B", "Street-pop",
    "Gospel", "Afro-house",
]


def register_cli(app):
    @app.cli.command("seed-genres")
    def seed_genres():
        """Insert starter genres (safe to run more than once)."""
        created = 0
        for name in STARTER_GENRES:
            try:
                genre_service.create_genre(name)
                created += 1
            except ConflictError:
                pass
        click.echo(f"Seeded {created} new genres ({len(STARTER_GENRES) - created} already existed).")

    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.option("--username", prompt=True)
    @click.password_option()
    def create_admin(email, username, password):
        """Create an administrator account."""
        try:
            user = auth_service.register_user(email, username, password)
        except AppError as err:
            details = "; ".join(f"{k}: {v}" for k, v in (err.details or {}).items())
            raise click.ClickException(f"{err.message} {details}".strip()) from err
        user.role = "admin"
        db.session.commit()
        click.echo(f"Administrator '{user.username}' created.")