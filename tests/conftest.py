import pytest

from app import create_app
from app.extensions import db


@pytest.fixture
def app():
    app = create_app("testing")
    uri = app.config["SQLALCHEMY_DATABASE_URI"] or ""
    assert uri.endswith("_test"), "Refusing to run tests against a non-test database"
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()