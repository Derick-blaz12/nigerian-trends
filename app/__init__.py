import os
from flask import Flask
from config import config


def create_app(config_name=None):
    config_name = config_name or os.environ.get("APP_ENV", "development")
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    from app.main import bp as main_bp
    app.register_blueprint(main_bp)

    return app