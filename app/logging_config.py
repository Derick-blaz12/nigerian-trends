import logging
import os
import time
import uuid
from logging.handlers import RotatingFileHandler

from flask import g, request


def configure_logging(app):
    level = getattr(logging, str(app.config["LOG_LEVEL"]).upper(), logging.INFO)
    app.logger.setLevel(level)

    if app.config.get("TESTING"):
        return  # pytest captures logs itself

    # create_app can run more than once per process; don't stack handlers.
    if any(getattr(h, "_trends_handler", False) for h in app.logger.handlers):
        return

    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console._trends_handler = True
    app.logger.addHandler(console)

    log_dir = app.config["LOG_DIR"]
    os.makedirs(log_dir, exist_ok=True)
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "app.log"), maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler._trends_handler = True
    app.logger.addHandler(file_handler)


def register_request_logging(app):
    @app.before_request
    def start_timer():
        g.request_id = uuid.uuid4().hex[:8]
        g.start_time = time.perf_counter()

    @app.after_request
    def log_request(response):
        started = g.get("start_time", time.perf_counter())
        duration_ms = (time.perf_counter() - started) * 1000
        request_id = g.get("request_id", "-")
        app.logger.info(
            "%s %s -> %s (%.1fms) [%s]",
            request.method, request.path, response.status_code, duration_ms, request_id,
        )
        response.headers["X-Request-ID"] = request_id
        return response