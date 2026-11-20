from datetime import timedelta

import click
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.collectors import lastfm_sync, sync
from app.collectors.http import PoliteClient
from app.collectors.lastfm import LastFmClient
from app.collectors.musicbrainz import MusicBrainzClient
from app.collectors.normalize import is_mbid
from app.collectors.runs import RunAlreadyActive
from app.errors import AppError, ConflictError
from app.extensions import db
from app.models import ArtistExternalId, CollectionRun
from app.models.mixins import utcnow
from app.radar.rules import DEFAULT_RULES
from app.services import artist_service, auth_service, genre_service, radar_service

STARTER_GENRES = [
    "Afrobeats", "Afropop", "Afro-fusion", "Amapiano", "Alté", "Highlife",
    "Fuji", "Juju", "Apala", "Hip-hop", "Afro-soul", "R&B", "Street-pop",
    "Gospel", "Afro-house",
]


def _fail(err):
    details = "; ".join(f"{k}: {v}" for k, v in (getattr(err, "details", None) or {}).items())
    return click.ClickException(f"{err.message} {details}".strip())


def _report(run):
    click.echo(
        f"Run {run.id}: {run.status}. Requests: {run.requests_made}. "
        f"Seen {run.items_seen}, created {run.items_created}, updated {run.items_updated}, "
        f"skipped {run.items_skipped}, failed {run.items_failed}."
    )
    if run.error_summary:
        click.echo(run.error_summary)
    if run.status == "failed":
        raise click.ClickException("The run failed.")  # non-zero exit so schedulers notice


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
        _report(run)

    @app.cli.command("collect-lastfm")
    @click.option("--limit", default=200, show_default=True, help="Max artists per run.")
    @click.option("--max-requests", default=300, show_default=True, help="Request budget.")
    @click.option("--scheduled", is_flag=True, help="Mark the run as started by a scheduler.")
    def collect_lastfm(limit, max_requests, scheduled):
        """Record today's Last.fm listener counts for artists linked to MusicBrainz."""
        api_key = (app.config.get("LASTFM_API_KEY") or "").strip()
        contact = (app.config.get("COLLECTOR_CONTACT") or "").strip()
        if not api_key:
            raise click.ClickException(
                "Set LASTFM_API_KEY in .env (free key: https://www.last.fm/api/account/create)."
            )
        if not contact:
            raise click.ClickException("Set COLLECTOR_CONTACT in .env.")
        http = PoliteClient(
            user_agent=f"NigerianTrends/0.1 ( {contact} )",
            min_interval=app.config["LASTFM_MIN_INTERVAL"],
            timeout=app.config["COLLECTOR_TIMEOUT"],
            max_attempts=app.config["COLLECTOR_MAX_ATTEMPTS"],
            max_requests=max_requests,
        )
        client = LastFmClient(http, api_key, app.config["LASTFM_BASE_URL"])
        try:
            run = lastfm_sync.run_lastfm(
                client, limit=limit, triggered_by="schedule" if scheduled else "cli"
            )
        except RunAlreadyActive as err:
            raise click.ClickException(str(err)) from err
        _report(run)

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

    @app.cli.command("link-musicbrainz")
    @click.option("--slug", prompt=True)
    @click.option("--mbid", prompt="MusicBrainz id")
    def link_musicbrainz(slug, mbid):
        """Link an artist to a MusicBrainz id that you have checked yourself."""
        mbid = mbid.strip().lower()
        if not is_mbid(mbid):
            raise click.ClickException("That is not a valid MusicBrainz id (like 78a19169-ac75-...).")
        try:
            artist = artist_service.get_artist_by_slug(slug)
        except AppError as err:
            raise _fail(err) from err
        source = sync.ensure_source()
        already = db.session.scalar(
            sa.select(ArtistExternalId.id).where(
                ArtistExternalId.artist_id == artist.id,
                ArtistExternalId.data_source_id == source.id,
            )
        )
        if already is not None:
            raise click.ClickException("This artist is already linked to MusicBrainz.")
        name = artist.name
        db.session.add(
            ArtistExternalId(artist_id=artist.id, data_source_id=source.id, external_id=mbid)
        )
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            raise click.ClickException("That MusicBrainz id is already linked to another artist.") from None
        click.echo(f"Linked '{name}'. Check it: https://musicbrainz.org/artist/{mbid}")

    @app.cli.command("radar-set")
    @click.option("--slug", prompt=True)
    @click.option("--status", type=click.Choice(["pick", "excluded", "clear"]), prompt=True)
    @click.option("--note", default="", help="Shown publicly for picks (max 200 characters).")
    @click.option("--days", type=int, default=None, help="Picks only: stop after this many days.")
    def radar_set(slug, status, note, days):
        """Pick an artist for the Radar, exclude one, or clear the choice."""
        try:
            artist = artist_service.get_artist_by_slug(slug)
            if status == "clear":
                removed = radar_service.clear_entry(artist)
                click.echo("Cleared." if removed else "There was nothing to clear.")
                return
            expires_on = None
            if days is not None:
                expires_on = (utcnow().date() + timedelta(days=days)).isoformat()
            radar_service.set_entry(artist, status, note or None, expires_on)
        except AppError as err:
            raise _fail(err) from err
        click.echo(f"Saved: {slug} is now '{status}'.")

    @app.cli.command("radar-show")
    @click.option("--limit", default=20, show_default=True)
    def radar_show(limit):
        """Print the current Radar with the reasons behind each artist."""
        items, total = radar_service.build_radar(limit)
        if not items:
            click.echo("The Radar is empty. Add artists, run the collectors, or make an editor's pick.")
            return
        click.echo(f"{total} artist(s) on the Radar.")
        for rank, (artist, _facts, evaluation) in enumerate(items, start=1):
            pick = "  [editor's pick]" if evaluation.editors_pick else ""
            click.echo(f"{rank}. {artist.name}  score {evaluation.score}{pick}")
            for component in evaluation.components:
                click.echo(f"     +{component.points} {component.detail}")

    @app.cli.command("radar-explain")
    @click.option("--slug", prompt=True)
    def radar_explain(slug):
        """Show why an artist is, or is not, on the Radar."""
        try:
            artist = artist_service.get_artist_by_slug(slug, include_archived=True)
            _, _facts, evaluation = radar_service.explain(artist.id)
        except AppError as err:
            raise _fail(err) from err
        verdict = "ON the Radar" if evaluation.appears else "NOT on the Radar"
        click.echo(
            f"{artist.name}: {verdict} (score {evaluation.score}, "
            f"needs {DEFAULT_RULES.min_score_to_appear} unless picked)"
        )
        for check in evaluation.checks:
            click.echo(f"  [{'ok' if check.passed else 'FAIL'}] {check.name}: {check.detail}")
        for component in evaluation.components:
            click.echo(f"  +{component.points} {component.name}: {component.detail}")