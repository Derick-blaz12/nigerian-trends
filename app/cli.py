import click

from app.errors import ConflictError
from app.services import genre_service

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