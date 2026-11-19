import click
import sqlalchemy as sa

from app.collectors import sync
from app.collectors.http import PoliteClient
from app.collectors.musicbrainz import MusicBrainzClient
from app.collectors.runs import RunAlreadyActive
from app.errors import AppError, ConflictError
from app.extensions import db
from app.models import CollectionRun
from app.services import artist_service, auth_service, genre_service

STARTER_GENRES = [
    "Afrobeats", "Afropop", "Afro-fusion", "Amapiano", "Alté", "Highlife",
    "Fuji", "Juju", "Apala", "Hip-hop", "Afro-soul", "R&B", "Street-pop",
    "Gospel", "Afro-house",
]


def _fail(err):
    details = "; ".join(f"{k}: {v}" for k, v in (getattr(err, "details", None) or {}).items())
    return click.ClickException(f"{err.message} {details}".strip())


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
            raise _fail(err) from err
        user.role = "admin"
        db.session.commit()
        click.echo(f"Administrator '{user.username}' created.")

    @app.cli.command("add-artist")
    @click.option("--name", prompt=True)
    def add_artist(name):
        """Add an artist by name (no admin login needed)."""
        try:
            artist = artist_service.create_artist({"name": name})
        except AppError as err:
            raise _fail(err) from err
        click.echo(f"Added '{artist.name}' (id {artist.id}, slug {artist.slug}).")

    @app.cli.command("collect-musicbrainz")
    @click.option("--limit", default=25, show_default=True, help="Max artists per stage.")
    @click.option("--max-requests", default=150, show_default=True, help="Request budget.")
    @click.option("--link/--no-link", default=True, help="Match artists to MusicBrainz.")
    @click.option("--enrich/--no-enrich", default=True, help="Import links and releases.")
    @click.option("--scheduled", is_flag=True, help="Mark the run as started by a scheduler.")
    def collect_musicbrainz(limit, max_requests, link, enrich, scheduled):
        """Run the MusicBrainz collection job."""
        contact = (app.config.get("COLLECTOR_CONTACT") or "").strip()
        if not contact:
            raise click.ClickException(
                "Set COLLECTOR_CONTACT in .env (an email or website MusicBrainz can reach)."
            )
        http = PoliteClient(
            user_agent=f"NigerianTrends/0.1 ( {contact} )",
            min_interval=app.config["COLLECTOR_MIN_INTERVAL"],
            timeout=app.config["COLLECTOR_TIMEOUT"],
            max_attempts=app.config["COLLECTOR_MAX_ATTEMPTS"],
            max_requests=max_requests,
        )
        client = MusicBrainzClient(http, app.config["MUSICBRAINZ_BASE_URL"])
        try:
            run = sync.run_musicbrainz(
                client,
                link=link,
                enrich=enrich,
                limit=limit,
                stale_days=app.config["COLLECTOR_STALE_DAYS"],
                triggered_by="schedule" if scheduled else "cli",
            )
        except RunAlreadyActive as err:
            raise click.ClickException(str(err)) from err

        click.echo(
            f"Run {run.id}: {run.status}. Requests: {run.requests_made}. "
            f"Seen {run.items_seen}, created {run.items_created}, updated {run.items_updated}, "
            f"skipped {run.items_skipped}, failed {run.items_failed}."
        )
        if run.error_summary:
            click.echo(run.error_summary)
        if run.status == "failed":
            raise click.ClickException("The run failed.")  # non-zero exit so schedulers notice

    @app.cli.command("collection-runs")
    def collection_runs():
        """Show the 10 most recent collection runs."""
        runs = db.session.scalars(
            sa.select(CollectionRun).order_by(CollectionRun.started_at.desc()).limit(10)
        ).all()
        if not runs:
            click.echo("No runs yet.")
        for run in runs:
            click.echo(
                f"#{run.id} {run.job} {run.status} ({run.triggered_by}) "
                f"started {run.started_at:%Y-%m-%d %H:%M} UTC | requests {run.requests_made} | "
                f"created {run.items_created}, updated {run.items_updated}, "
                f"skipped {run.items_skipped}, failed {run.items_failed}"
            )