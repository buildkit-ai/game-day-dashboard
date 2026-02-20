"""
Thin wrapper around the Shipp.ai API for real-time sports data.

Handles connection lifecycle, cursor-based polling, and rate-limit retries.
Connections are reused across polls — create once, poll many times.
"""

import os
import time
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

SHIPP_BASE_URL = "https://api.shipp.ai/api/v1"
DEFAULT_POLL_TIMEOUT = 45  # seconds (connections can take time)
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds


class ShippConnectionError(Exception):
    """Raised when a Shipp API connection fails."""
    pass


class ShippRateLimitError(Exception):
    """Raised when Shipp returns 429 Too Many Requests."""
    pass


# Maps sport key to a natural-language filter_instructions for Shipp
FILTER_INSTRUCTIONS = {
    "nba": "Track all NBA games today including scores, play-by-play, and game status updates",
    "mlb": "Track all MLB games today including scores, play-by-play, and pitching changes",
    "soccer": "Track all soccer matches today across major leagues including goals, cards, and substitutions",
}


class ShippConnection:
    """
    Represents a single Shipp data connection for a sport.

    Usage:
        conn = ShippConnection(api_key, sport="nba")
        conn.create()
        while True:
            data = conn.poll()
            process(data)
            time.sleep(10)
    """

    def __init__(self, api_key: str, sport: str, league: Optional[str] = None):
        self.api_key = api_key
        self.sport = sport.lower()
        self.league = league
        self.connection_id: Optional[str] = None
        self.last_event_id: Optional[str] = None
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "User-Agent": "game-day-dashboard/1.0",
        })
        self._created_at: Optional[float] = None

    def _url(self, path: str) -> str:
        """Build URL with api_key query parameter."""
        sep = "&" if "?" in path else "?"
        return f"{SHIPP_BASE_URL}{path}{sep}api_key={self.api_key}"

    def create(self, filter_instructions: Optional[str] = None) -> str:
        """
        Create a new Shipp connection using filter_instructions.
        Returns the connection ID.
        """
        instructions = filter_instructions or FILTER_INSTRUCTIONS.get(
            self.sport,
            f"Track all {self.sport} games today with scores and play-by-play"
        )

        payload = {
            "filter_instructions": instructions,
        }

        response = self._request_with_retry(
            "POST",
            self._url("/connections/create"),
            json=payload,
        )

        data = response.json()
        self.connection_id = data.get("connection_id") or data.get("id")
        if not self.connection_id:
            raise ShippConnectionError(
                f"No connection ID in response: {data}"
            )

        self._created_at = time.time()
        self.last_event_id = None
        logger.info(
            "Created Shipp connection %s for %s",
            self.connection_id,
            self.sport,
        )
        return self.connection_id

    def attach(self, connection_id: str):
        """Attach to an existing connection by ID (skip create)."""
        self.connection_id = connection_id
        self._created_at = time.time()
        self.last_event_id = None

    def poll(self) -> dict:
        """
        Poll the connection for new events since the last poll.

        Returns the full response dict. Live data is in 'data' array.
        Uses cursor-based pagination via since_event_id.
        """
        if not self.connection_id:
            raise ShippConnectionError(
                "Connection not created. Call create() first."
            )

        payload = {"limit": 50}
        if self.last_event_id:
            payload["since_event_id"] = self.last_event_id

        response = self._request_with_retry(
            "POST",
            self._url(f"/connections/{self.connection_id}"),
            json=payload,
        )

        data = response.json()

        # Update cursor from the latest event in data[]
        events = data.get("data", [])
        if events:
            last = events[-1]
            new_cursor = last.get("id") or last.get("event_id")
            if new_cursor:
                self.last_event_id = str(new_cursor)

        return data

    def close(self):
        """Clean up resources (Shipp connections persist server-side for reuse)."""
        self.connection_id = None
        self.last_event_id = None

    @property
    def is_active(self) -> bool:
        return self.connection_id is not None

    @property
    def age_seconds(self) -> float:
        if self._created_at is None:
            return 0.0
        return time.time() - self._created_at

    def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> requests.Response:
        """
        Make an HTTP request with automatic retry on transient failures.
        Handles 429 (rate limit) and 5xx (server errors) with exponential backoff.
        """
        kwargs.setdefault("timeout", DEFAULT_POLL_TIMEOUT)
        last_exception = None

        for attempt in range(MAX_RETRIES):
            try:
                response = self.session.request(method, url, **kwargs)

                if response.status_code == 429:
                    retry_after = int(
                        response.headers.get("Retry-After", RETRY_BACKOFF_BASE)
                    )
                    wait = retry_after * (attempt + 1)
                    logger.warning(
                        "Rate limited (429). Waiting %ds before retry %d/%d",
                        wait,
                        attempt + 1,
                        MAX_RETRIES,
                    )
                    time.sleep(wait)
                    continue

                if response.status_code >= 500:
                    wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                    logger.warning(
                        "Server error %d. Waiting %ds before retry %d/%d",
                        response.status_code,
                        wait,
                        attempt + 1,
                        MAX_RETRIES,
                    )
                    time.sleep(wait)
                    continue

                response.raise_for_status()
                return response

            except requests.exceptions.Timeout as exc:
                last_exception = exc
                wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                logger.warning(
                    "Request timeout. Waiting %ds before retry %d/%d",
                    wait,
                    attempt + 1,
                    MAX_RETRIES,
                )
                time.sleep(wait)

            except requests.exceptions.ConnectionError as exc:
                last_exception = exc
                wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                logger.warning(
                    "Connection error. Waiting %ds before retry %d/%d",
                    wait,
                    attempt + 1,
                    MAX_RETRIES,
                )
                time.sleep(wait)

        raise ShippConnectionError(
            f"Request to {url} failed after {MAX_RETRIES} retries: "
            f"{last_exception}"
        )


class ShippManager:
    """
    Manages multiple Shipp connections and schedule lookups.

    Usage:
        manager = ShippManager()
        schedule = manager.get_schedule("nba")
        manager.connect("nba")
        data = manager.poll_all()
    """

    SPORT_CONFIG = {
        "nba": {"display": "NBA", "league": None},
        "mlb": {"display": "MLB", "league": None},
        "soccer": {"display": "Soccer", "league": None},
    }

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("SHIPP_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "SHIPP_API_KEY is required. Set it as an environment variable "
                "or pass it directly. Get a free key at platform.shipp.ai"
            )
        self.connections: dict[str, ShippConnection] = {}
        self.session = requests.Session()

    def get_schedule(self, sport: str) -> list[dict]:
        """
        Fetch schedule for a sport (free endpoint, no credits).
        Returns list of game dicts.
        """
        url = f"{SHIPP_BASE_URL}/sports/{sport}/schedule?api_key={self.api_key}"
        try:
            r = self.session.get(url, timeout=30)
            r.raise_for_status()
            data = r.json()
            return data.get("schedule", data.get("data", []))
        except Exception as exc:
            logger.warning("Failed to fetch %s schedule: %s", sport, exc)
            return []

    def list_connections(self) -> list[dict]:
        """List all existing connections (free endpoint)."""
        url = f"{SHIPP_BASE_URL}/connections?api_key={self.api_key}"
        try:
            r = self.session.get(url, timeout=15)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list):
                return data
            return data.get("connections", data.get("data", []))
        except Exception as exc:
            logger.warning("Failed to list connections: %s", exc)
            return []

    def connect(self, sport: str, league: Optional[str] = None) -> str:
        """Create a connection for a sport. Returns connection ID."""
        key = f"{sport}:{league}" if league else sport
        if key in self.connections and self.connections[key].is_active:
            logger.info("Reusing existing connection for %s", key)
            return self.connections[key].connection_id

        conn = ShippConnection(self.api_key, sport, league)
        conn.create()
        self.connections[key] = conn
        return conn.connection_id

    def attach(self, sport: str, connection_id: str):
        """Attach to an existing connection ID for a sport."""
        conn = ShippConnection(self.api_key, sport)
        conn.attach(connection_id)
        self.connections[sport] = conn

    def poll_all(self) -> dict[str, dict]:
        """
        Poll all active connections. Returns {sport_key: response_data}.
        """
        results = {}
        for key, conn in list(self.connections.items()):
            if not conn.is_active:
                continue
            try:
                results[key] = conn.poll()
            except ShippConnectionError as exc:
                logger.error("Poll failed for %s: %s", key, exc)
                results[key] = {"data": [], "error": str(exc)}
            except Exception as exc:
                logger.error("Unexpected error polling %s: %s", key, exc)
                results[key] = {"data": [], "error": str(exc)}
        return results

    def close_all(self):
        """Close all active connections."""
        for key, conn in self.connections.items():
            conn.close()
        self.connections.clear()

    def connected_sports(self) -> list[str]:
        """List of sport keys with active connections."""
        return [k for k, c in self.connections.items() if c.is_active]
