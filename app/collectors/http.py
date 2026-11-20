import logging
import random
import time

import requests

logger = logging.getLogger(__name__)


class CollectorError(Exception):
    """An external source could not give us what we asked for."""


class BudgetExceeded(CollectorError):
    """This run has used up its request budget."""


class PoliteClient:
    """GET JSON from an API: identifies itself, spaces out requests, retries politely."""

    def __init__(self, user_agent, min_interval=1.1, timeout=20, max_attempts=4,
                 max_requests=None, session=None, clock=time.monotonic,
                 sleep=time.sleep, jitter=random.random):
        self.headers = {"User-Agent": user_agent, "Accept": "application/json"}
        self.min_interval = min_interval
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.max_requests = max_requests
        self.session = session or requests.Session()
        self.clock = clock
        self.sleep = sleep
        self.jitter = jitter
        self.requests_made = 0
        self._last_request_at = None

    def _wait_turn(self):
        if self._last_request_at is not None:
            wait = self.min_interval - (self.clock() - self._last_request_at)
            if wait > 0:
                self.sleep(wait)
        self._last_request_at = self.clock()

    @staticmethod
    def _retry_after(value):
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            return None
        return max(0.0, min(seconds, 60.0))

    def _backoff(self, attempt, retry_after, reason):
        delay = self._retry_after(retry_after)
        if delay is None:
            delay = min(60.0, 2.0 ** attempt + self.jitter())
        logger.warning("%s (attempt %s of %s)", reason, attempt, self.max_attempts)
        if attempt < self.max_attempts:
            self.sleep(delay)

    def get_json(self, url, params=None, accept_client_errors=False):
        """Return parsed JSON, or None if the resource doesn't exist (404).

        With accept_client_errors=True, a 4xx response that carries a JSON body is returned
        instead of raising, for APIs that report their errors as JSON.
        """
        for attempt in range(1, self.max_attempts + 1):
            if self.max_requests is not None and self.requests_made >= self.max_requests:
                raise BudgetExceeded(f"Request budget of {self.max_requests} used up.")
            self._wait_turn()
            self.requests_made += 1
            try:
                response = self.session.get(
                    url, params=params, headers=self.headers, timeout=self.timeout
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                self._backoff(attempt, None, f"Network error: {exc.__class__.__name__}")
                continue

            status = response.status_code
            if status == 200:
                try:
                    return response.json()
                except ValueError:
                    raise CollectorError(f"Invalid JSON from {url}") from None
            if status == 429 or status >= 500:
                self._backoff(attempt, response.headers.get("Retry-After"), f"HTTP {status}")
                continue
            if accept_client_errors and 400 <= status < 500:
                try:
                    return response.json()
                except ValueError:
                    raise CollectorError(f"HTTP {status} from {url}") from None
            if status == 404:
                return None
            raise CollectorError(f"HTTP {status} from {url}")

        raise CollectorError(f"Gave up on {url} after {self.max_attempts} attempts.")