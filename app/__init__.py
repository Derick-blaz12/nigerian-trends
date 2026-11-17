import os

from flask import Flask

from app.errors import register_error_handlers
from app.extensions import db, migrate
from app.logging_config import configure_logging, register_request_logging
from config import config


def create_app(config_name=None):
    config_name = config_name or os.environ.get("APP_ENV", "development")
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    if config_name == "production" and not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY must be set in production.")

    configure_logging(app)
    register_request_logging(app)

    db.init_app(app)
    migrate.init_app(app, db)
    from app import models  # noqa: F401  (registers tables with SQLAlchemy)

    from app.api import bp as api_bp
    from app.main import bp as main_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)

    register_error_handlers(app)

    from app.cli import register_cli
    register_cli(app)

    return app