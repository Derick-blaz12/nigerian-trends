import os
from datetime import timedelta

from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    LOG_DIR = os.path.join(basedir, "logs")

    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE = 100

    # Request size limits
    MAX_CONTENT_LENGTH = 6 * 1024 * 1024  # hard ceiling for any request
    MAX_JSON_BYTES = 1024 * 1024          # JSON bodies
    MAX_IMAGE_BYTES = 5 * 1024 * 1024     # image uploads

    # Media storage: local disk for now, object storage in Phase 14
    UPLOAD_DIR = os.environ.get("UPLOAD_DIR", os.path.join(basedir, "uploads"))
    MEDIA_URL = "/media"

    # Sessions and cookies
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False  # True in production (HTTPS only)
    PERMANENT_SESSION_LIFETIME = timedelta(days=14)

    # CSRF: token stays valid for the whole session, so a page left open
    # for hours doesn't fail on submit.
    WTF_CSRF_TIME_LIMIT = None

    # Rate limiting (in-memory for now; production will use Redis in Phase 14)
    RATELIMIT_ENABLED = True
    RATELIMIT_STORAGE_URI = "memory://"

    # Data collection (Phase 8)
    COLLECTOR_CONTACT = os.environ.get("COLLECTOR_CONTACT", "")
    MUSICBRAINZ_BASE_URL = "https://musicbrainz.org/ws/2"
    COLLECTOR_MIN_INTERVAL = 1.1   # seconds between requests (the source allows 1 per second)
    COLLECTOR_TIMEOUT = 20
    COLLECTOR_MAX_ATTEMPTS = 4
    COLLECTOR_STALE_DAYS = 30      # re-enrich an artist after this many days


class DevelopmentConfig(Config):
    DEBUG = True
    LOG_LEVEL = "DEBUG"


class TestingConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL")
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True


config = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}