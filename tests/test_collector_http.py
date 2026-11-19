import pytest
import requests

from app.collectors.http import BudgetExceeded, CollectorError
from tests.collector_fakes import FakeResponse, make_http

URL = "https://example.test/ws"


def test_sends_user_agent_and_returns_json():
    http, session, _ = make_http(FakeResponse(200, {"ok": True}))

    assert http.get_json(URL, {"a": 1}) == {"ok": True}

    call = session.calls[0]
    assert "test@example.com" in call["headers"]["User-Agent"]
    assert call["params"] == {"a": 1}
    assert call["timeout"] == 20
    assert http.requests_made == 1


def test_requests_are_spaced_apart():
    http, _, clock = make_http(FakeResponse(200, {}), FakeResponse(200, {}))
    http.get_json(URL)
    http.get_json(URL)
    assert clock.sleeps == [pytest.approx(1.1)]


def test_retries_a_503_with_backoff():
    http, session, clock = make_http(FakeResponse(503), FakeResponse(200, {"ok": 1}))

    assert http.get_json(URL) == {"ok": 1}
    assert len(session.calls) == 2
    assert clock.sleeps == [2.0]


def test_honours_retry_after():
    http, _, clock = make_http(FakeResponse(429, headers={"Retry-After": "7"}), FakeResponse(200, {}))
    http.get_json(URL)
    assert clock.sleeps == [7.0]


def test_retries_network_errors():
    http, session, _ = make_http(requests.ConnectionError("boom"), FakeResponse(200, {"ok": 1}))
    assert http.get_json(URL) == {"ok": 1}
    assert len(session.calls) == 2


def test_gives_up_after_max_attempts():
    http, session, clock = make_http(
        FakeResponse(503), FakeResponse(503), FakeResponse(503), max_attempts=3
    )
    with pytest.raises(CollectorError):
        http.get_json(URL)
    assert len(session.calls) == 3
    assert clock.sleeps == [2.0, 4.0]


def test_404_returns_none_without_retrying():
    http, session, _ = make_http(FakeResponse(404, {"error": "Not Found"}))
    assert http.get_json(URL) is None
    assert len(session.calls) == 1


def test_client_errors_are_not_retried():
    http, session, _ = make_http(FakeResponse(400, {"error": "bad"}))
    with pytest.raises(CollectorError):
        http.get_json(URL)
    assert len(session.calls) == 1


def test_invalid_json_is_an_error():
    http, _, _ = make_http(FakeResponse(200, None))
    with pytest.raises(CollectorError):
        http.get_json(URL)


def test_request_budget_is_enforced_even_across_retries():
    http, session, _ = make_http(
        FakeResponse(503), FakeResponse(503), FakeResponse(200, {}), max_requests=2
    )
    with pytest.raises(BudgetExceeded):
        http.get_json(URL)
    assert len(session.calls) == 2