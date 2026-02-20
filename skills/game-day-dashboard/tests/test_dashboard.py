"""
Comprehensive tests for the Game Day Dashboard.

Tests cover:
  - GameState data model
  - parse_game_data (various sports, nested/flat teams, missing fields)
  - parse_events (score updates, play-by-play, status changes)
  - build_dashboard rendering (live-only filter, no games, mixed statuses)
  - ShippConnection (create, poll, close, retry logic)
  - ShippManager (connect, poll_all, close_all, connection reuse)
  - Helper functions (_safe_int, _format_start_time)
  - Error handling paths
"""

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

import requests

# Ensure scripts directory is on sys.path so we can import the modules
SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
sys.path.insert(0, SCRIPTS_DIR)

from shipp_wrapper import (
    ShippConnection,
    ShippConnectionError,
    ShippManager,
    ShippRateLimitError,
    SHIPP_BASE_URL,
    MAX_RETRIES,
)
from dashboard import (
    GameState,
    parse_game_data,
    parse_events,
    build_dashboard,
    _safe_int,
    _format_start_time,
    MAX_PLAYS_PER_GAME,
)


# ---------------------------------------------------------------------------
# GameState model tests
# ---------------------------------------------------------------------------


class TestGameState(unittest.TestCase):
    """Tests for the GameState data model."""

    def test_initial_defaults(self):
        """GameState initializes with sensible defaults."""
        gs = GameState("g1", "nba")
        self.assertEqual(gs.game_id, "g1")
        self.assertEqual(gs.sport, "nba")
        self.assertEqual(gs.home_team, "HOME")
        self.assertEqual(gs.away_team, "AWAY")
        self.assertEqual(gs.home_score, 0)
        self.assertEqual(gs.away_score, 0)
        self.assertEqual(gs.status, "scheduled")
        self.assertEqual(gs.period, "")
        self.assertEqual(gs.clock, "")
        self.assertIsNone(gs.start_time)
        self.assertEqual(gs.recent_plays, [])

    def test_display_status_final(self):
        """display_status returns 'FINAL' when status is final."""
        gs = GameState("g1", "nba")
        gs.status = "final"
        self.assertEqual(gs.display_status, "FINAL")

    def test_display_status_scheduled_with_start_time(self):
        """display_status returns start_time string when scheduled and start_time is set."""
        gs = GameState("g1", "nba")
        gs.status = "scheduled"
        gs.start_time = "07:30 PM"
        self.assertEqual(gs.display_status, "07:30 PM")

    def test_display_status_scheduled_no_start_time(self):
        """display_status returns 'SCHED' when scheduled and no start_time."""
        gs = GameState("g1", "nba")
        gs.status = "scheduled"
        self.assertEqual(gs.display_status, "SCHED")

    def test_display_status_live_with_period_and_clock(self):
        """display_status shows period and clock for live games."""
        gs = GameState("g1", "nba")
        gs.status = "live"
        gs.period = "Q3"
        gs.clock = "4:32"
        self.assertEqual(gs.display_status, "Q3  4:32")

    def test_display_status_live_no_period_no_clock(self):
        """display_status returns 'LIVE' when live but no period/clock set."""
        gs = GameState("g1", "nba")
        gs.status = "live"
        self.assertEqual(gs.display_status, "LIVE")

    def test_score_line(self):
        """score_line formats correctly."""
        gs = GameState("g1", "nba")
        gs.away_team = "BOS"
        gs.home_team = "LAL"
        gs.away_score = 102
        gs.home_score = 98
        self.assertEqual(gs.score_line, "BOS 102 - 98 LAL")

    def test_add_play_trims_to_max(self):
        """add_play keeps only the last MAX_PLAYS_PER_GAME plays."""
        gs = GameState("g1", "nba")
        for i in range(10):
            gs.add_play(f"Play {i}")
        self.assertEqual(len(gs.recent_plays), MAX_PLAYS_PER_GAME)
        self.assertEqual(gs.recent_plays[-1], "Play 9")
        self.assertEqual(gs.recent_plays[0], f"Play {10 - MAX_PLAYS_PER_GAME}")


# ---------------------------------------------------------------------------
# parse_game_data tests
# ---------------------------------------------------------------------------


class TestParseGameData(unittest.TestCase):
    """Tests for parse_game_data across different sports and data shapes."""

    def test_nba_nested_teams(self):
        """Parse NBA game with nested team dicts."""
        game = {
            "game_id": "nba-001",
            "home_team": {"abbreviation": "LAL", "name": "Lakers"},
            "away_team": {"abbreviation": "BOS", "name": "Celtics"},
            "home_score": 110,
            "away_score": 105,
            "status": "live",
            "period": 3,
            "clock": "2:45",
        }
        state = parse_game_data(game, "nba")
        self.assertEqual(state.game_id, "nba-001")
        self.assertEqual(state.home_team, "LAL")
        self.assertEqual(state.away_team, "BOS")
        self.assertEqual(state.home_score, 110)
        self.assertEqual(state.away_score, 105)
        self.assertEqual(state.status, "live")
        self.assertEqual(state.period, "Q3")
        self.assertEqual(state.clock, "2:45")

    def test_nba_overtime_period(self):
        """NBA period > 4 should render as OT."""
        game = {
            "game_id": "nba-002",
            "home_team": "LAL",
            "away_team": "BOS",
            "status": "live",
            "period": 5,
        }
        state = parse_game_data(game, "nba")
        self.assertEqual(state.period, "OT1")

    def test_mlb_inning_top(self):
        """Parse MLB game with inning half = top."""
        game = {
            "game_id": "mlb-001",
            "home_team": "NYY",
            "away_team": "BOS",
            "home_score": 3,
            "away_score": 2,
            "status": "in_progress",
            "inning": 7,
            "half": "top",
            "outs": 2,
        }
        state = parse_game_data(game, "mlb")
        self.assertEqual(state.period, "Top 7")
        self.assertEqual(state.clock, "2 outs")
        self.assertEqual(state.status, "live")

    def test_mlb_single_out(self):
        """MLB 1 out should be singular ('1 out', not '1 outs')."""
        game = {
            "game_id": "mlb-002",
            "home_team": "NYY",
            "away_team": "BOS",
            "status": "active",
            "inning": 3,
            "half": "bottom",
            "outs": 1,
        }
        state = parse_game_data(game, "mlb")
        self.assertEqual(state.clock, "1 out")

    def test_soccer_minute(self):
        """Parse soccer game with minute field."""
        game = {
            "id": "soc-001",
            "home": {"name": "Arsenal"},
            "away": {"name": "Chelsea"},
            "homeScore": 1,
            "awayScore": 0,
            "state": "active",
            "minute": 67,
        }
        state = parse_game_data(game, "soccer")
        self.assertEqual(state.game_id, "soc-001")
        self.assertEqual(state.home_team, "Arsenal")
        self.assertEqual(state.away_team, "Chelsea")
        self.assertEqual(state.period, "67'")
        self.assertEqual(state.status, "live")

    def test_flat_string_teams(self):
        """Teams given as flat strings instead of dicts."""
        game = {
            "game_id": "x1",
            "home_team": "Team A",
            "away_team": "Team B",
            "status": "scheduled",
        }
        state = parse_game_data(game, "nba")
        self.assertEqual(state.home_team, "Team A")
        self.assertEqual(state.away_team, "Team B")

    def test_missing_fields_default_gracefully(self):
        """Entirely empty game dict still returns a valid GameState."""
        state = parse_game_data({}, "nba")
        self.assertEqual(state.game_id, "unknown")
        self.assertEqual(state.home_team, "HOME")
        self.assertEqual(state.away_team, "AWAY")
        self.assertEqual(state.home_score, 0)
        self.assertEqual(state.away_score, 0)
        self.assertEqual(state.status, "scheduled")

    def test_final_status_variants(self):
        """Various final-status strings should all map to 'final'."""
        for raw in ("final", "finished", "completed", "closed"):
            game = {"game_id": "g1", "status": raw}
            state = parse_game_data(game, "nba")
            self.assertEqual(state.status, "final", f"Failed for status='{raw}'")

    def test_start_time_formatted(self):
        """An ISO start_time should be formatted."""
        game = {
            "game_id": "g1",
            "start_time": "2026-02-18T19:30:00Z",
            "status": "scheduled",
        }
        state = parse_game_data(game, "nba")
        # It should contain PM since 19:30 UTC is afternoon/evening
        self.assertIsNotNone(state.start_time)
        self.assertIn(":", state.start_time)


# ---------------------------------------------------------------------------
# parse_events tests
# ---------------------------------------------------------------------------


class TestParseEvents(unittest.TestCase):
    """Tests for parse_events updating game states in place."""

    def _make_game(self, game_id="g1", sport="nba"):
        gs = GameState(game_id, sport)
        gs.home_team = "LAL"
        gs.away_team = "BOS"
        gs.status = "live"
        return gs

    def test_score_update(self):
        """Events with scores should update game scores."""
        games = {"g1": self._make_game()}
        events = [
            {"game_id": "g1", "home_score": 55, "away_score": 48},
        ]
        parse_events(events, games, "nba")
        self.assertEqual(games["g1"].home_score, 55)
        self.assertEqual(games["g1"].away_score, 48)

    def test_play_description_added(self):
        """Events with description add plays."""
        games = {"g1": self._make_game()}
        events = [
            {"game_id": "g1", "description": "LeBron dunk!"},
        ]
        parse_events(events, games, "nba")
        self.assertIn("LeBron dunk!", games["g1"].recent_plays)

    def test_status_change_to_final(self):
        """An event with status=final should set game to final."""
        games = {"g1": self._make_game()}
        events = [{"game_id": "g1", "status": "final"}]
        parse_events(events, games, "nba")
        self.assertEqual(games["g1"].status, "final")

    def test_event_for_unknown_game_ignored(self):
        """Events referencing unknown game IDs should not raise."""
        games = {"g1": self._make_game()}
        events = [
            {"game_id": "g999", "description": "Ghost play"},
        ]
        # Should not raise
        parse_events(events, games, "nba")
        self.assertNotIn("g999", games)

    def test_period_and_clock_update(self):
        """Events can update period and clock."""
        games = {"g1": self._make_game()}
        events = [
            {"game_id": "g1", "period": "4", "clock": "1:30"},
        ]
        parse_events(events, games, "nba")
        self.assertEqual(games["g1"].period, "4")
        self.assertEqual(games["g1"].clock, "1:30")


# ---------------------------------------------------------------------------
# build_dashboard rendering tests
# ---------------------------------------------------------------------------


class TestBuildDashboard(unittest.TestCase):
    """Tests for dashboard rendering."""

    def test_no_games_returns_panel(self):
        """build_dashboard with empty games still returns a Panel."""
        from rich.panel import Panel
        panel = build_dashboard({})
        self.assertIsInstance(panel, Panel)

    def test_live_only_filters_scheduled(self):
        """live_only=True excludes scheduled games from rendering."""
        nba_games = {
            "g1": self._make_game("g1", status="live"),
            "g2": self._make_game("g2", status="scheduled"),
        }
        all_games = {"nba": nba_games}
        panel = build_dashboard(all_games, live_only=True)
        # The panel should be generated without error
        from rich.panel import Panel
        self.assertIsInstance(panel, Panel)

    def test_mixed_sports(self):
        """Dashboard with games from multiple sports renders fine."""
        all_games = {
            "nba": {"g1": self._make_game("g1", status="live")},
            "mlb": {"g2": self._make_game("g2", status="final")},
            "soccer": {"g3": self._make_game("g3", status="scheduled")},
        }
        from rich.panel import Panel
        panel = build_dashboard(all_games)
        self.assertIsInstance(panel, Panel)

    def _make_game(self, gid, status="live"):
        gs = GameState(gid, "nba")
        gs.home_team = "LAL"
        gs.away_team = "BOS"
        gs.home_score = 100
        gs.away_score = 95
        gs.status = status
        return gs


# ---------------------------------------------------------------------------
# ShippConnection tests
# ---------------------------------------------------------------------------


class TestShippConnection(unittest.TestCase):
    """Tests for the ShippConnection class (all HTTP mocked)."""

    def _make_conn(self):
        return ShippConnection(api_key="test-key", sport="nba")

    @patch.object(requests.Session, "request")
    def test_create_success(self, mock_request):
        """create() stores the connection_id from the API response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"connection_id": "conn-abc"}
        mock_response.raise_for_status = MagicMock()
        mock_request.return_value = mock_response

        conn = self._make_conn()
        cid = conn.create()

        self.assertEqual(cid, "conn-abc")
        self.assertEqual(conn.connection_id, "conn-abc")
        self.assertTrue(conn.is_active)
        mock_request.assert_called_once()

    @patch.object(requests.Session, "request")
    def test_create_no_id_raises(self, mock_request):
        """create() raises ShippConnectionError when response lacks an id."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok"}
        mock_response.raise_for_status = MagicMock()
        mock_request.return_value = mock_response

        conn = self._make_conn()
        with self.assertRaises(ShippConnectionError):
            conn.create()

    @patch.object(requests.Session, "request")
    def test_poll_success_with_cursor(self, mock_request):
        """poll() updates last_event_id from events list."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "connection_id": "conn-abc",
            "data": [
                {"id": "evt-1", "description": "Play 1"},
                {"id": "evt-2", "description": "Play 2"},
            ],
        }
        mock_response.raise_for_status = MagicMock()
        mock_request.return_value = mock_response

        conn = self._make_conn()
        conn.connection_id = "conn-abc"

        data = conn.poll()

        self.assertEqual(len(data["data"]), 2)
        self.assertEqual(conn.last_event_id, "evt-2")

    def test_poll_without_create_raises(self):
        """poll() raises ShippConnectionError if create() was not called."""
        conn = self._make_conn()
        with self.assertRaises(ShippConnectionError):
            conn.poll()

    @patch.object(requests.Session, "request")
    def test_close_clears_state(self, mock_request):
        """close() sends request and clears connection_id."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        mock_response.raise_for_status = MagicMock()
        mock_request.return_value = mock_response

        conn = self._make_conn()
        conn.connection_id = "conn-abc"
        conn.last_event_id = "evt-1"
        conn.close()

        self.assertIsNone(conn.connection_id)
        self.assertIsNone(conn.last_event_id)
        self.assertFalse(conn.is_active)

    @patch("time.sleep", return_value=None)
    @patch.object(requests.Session, "request")
    def test_retry_on_500(self, mock_request, mock_sleep):
        """Server errors (500) trigger retries with backoff."""
        error_resp = MagicMock()
        error_resp.status_code = 500
        error_resp.raise_for_status = MagicMock()

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {"connection_id": "conn-ok"}
        ok_resp.raise_for_status = MagicMock()

        mock_request.side_effect = [error_resp, ok_resp]

        conn = self._make_conn()
        cid = conn.create()

        self.assertEqual(cid, "conn-ok")
        self.assertEqual(mock_request.call_count, 2)
        mock_sleep.assert_called()  # backoff was used

    @patch("time.sleep", return_value=None)
    @patch.object(requests.Session, "request")
    def test_retry_on_429(self, mock_request, mock_sleep):
        """Rate limit (429) triggers retries with Retry-After."""
        rate_resp = MagicMock()
        rate_resp.status_code = 429
        rate_resp.headers = {"Retry-After": "1"}

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {"connection_id": "conn-ok"}
        ok_resp.raise_for_status = MagicMock()

        mock_request.side_effect = [rate_resp, ok_resp]

        conn = self._make_conn()
        cid = conn.create()

        self.assertEqual(cid, "conn-ok")
        self.assertEqual(mock_request.call_count, 2)

    @patch("time.sleep", return_value=None)
    @patch.object(requests.Session, "request")
    def test_max_retries_exhausted_raises(self, mock_request, mock_sleep):
        """All retries exhausted raises ShippConnectionError."""
        mock_request.side_effect = requests.exceptions.Timeout("timeout")

        conn = self._make_conn()
        with self.assertRaises(ShippConnectionError):
            conn.create()

        self.assertEqual(mock_request.call_count, MAX_RETRIES)

    @patch("time.sleep", return_value=None)
    @patch.object(requests.Session, "request")
    def test_retry_on_connection_error(self, mock_request, mock_sleep):
        """ConnectionError triggers retries."""
        conn_err = requests.exceptions.ConnectionError("refused")
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {"connection_id": "conn-ok"}
        ok_resp.raise_for_status = MagicMock()

        mock_request.side_effect = [conn_err, ok_resp]

        conn = self._make_conn()
        cid = conn.create()
        self.assertEqual(cid, "conn-ok")

    def test_age_seconds_zero_before_create(self):
        """age_seconds is 0.0 before create is called."""
        conn = self._make_conn()
        self.assertEqual(conn.age_seconds, 0.0)


# ---------------------------------------------------------------------------
# ShippManager tests
# ---------------------------------------------------------------------------


class TestShippManager(unittest.TestCase):
    """Tests for ShippManager (all HTTP mocked)."""

    def _make_ok_response(self, json_data):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = json_data
        resp.raise_for_status = MagicMock()
        return resp

    @patch.dict(os.environ, {"SHIPP_API_KEY": ""}, clear=False)
    def test_missing_api_key_raises(self):
        """ShippManager raises ValueError without an API key."""
        with self.assertRaises(ValueError):
            ShippManager(api_key="")

    @patch.dict(os.environ, {"SHIPP_API_KEY": "test-key"}, clear=False)
    @patch.object(requests.Session, "request")
    def test_connect_creates_connection(self, mock_request):
        """connect() creates a connection and stores it."""
        mock_request.return_value = self._make_ok_response(
            {"connection_id": "conn-nba"}
        )
        manager = ShippManager()
        cid = manager.connect("nba")
        self.assertEqual(cid, "conn-nba")
        self.assertIn("nba", manager.connections)

    @patch.dict(os.environ, {"SHIPP_API_KEY": "test-key"}, clear=False)
    @patch.object(requests.Session, "request")
    def test_connection_reuse(self, mock_request):
        """Connecting to same sport twice reuses existing connection."""
        mock_request.return_value = self._make_ok_response(
            {"connection_id": "conn-nba"}
        )
        manager = ShippManager()
        cid1 = manager.connect("nba")
        cid2 = manager.connect("nba")
        self.assertEqual(cid1, cid2)
        # create() should only be called once
        self.assertEqual(mock_request.call_count, 1)

    @patch.dict(os.environ, {"SHIPP_API_KEY": "test-key"}, clear=False)
    @patch.object(requests.Session, "request")
    def test_poll_all_returns_data(self, mock_request):
        """poll_all returns data from all active connections."""
        create_resp = self._make_ok_response({"connection_id": "conn-nba"})
        poll_resp = self._make_ok_response(
            {"connection_id": "conn-nba", "data": [{"game_id": "g1"}]}
        )
        mock_request.side_effect = [create_resp, poll_resp]

        manager = ShippManager()
        manager.connect("nba")
        results = manager.poll_all()

        self.assertIn("nba", results)
        self.assertEqual(len(results["nba"]["data"]), 1)

    @patch.dict(os.environ, {"SHIPP_API_KEY": "test-key"}, clear=False)
    @patch.object(requests.Session, "request")
    def test_poll_all_handles_error_gracefully(self, mock_request):
        """poll_all returns error dict when a connection poll fails."""
        create_resp = self._make_ok_response({"connection_id": "conn-nba"})
        mock_request.side_effect = [create_resp]

        manager = ShippManager()
        manager.connect("nba")

        # Now make the poll fail
        mock_request.side_effect = requests.exceptions.Timeout("timeout")

        with patch("time.sleep", return_value=None):
            results = manager.poll_all()

        self.assertIn("nba", results)
        self.assertIn("error", results["nba"])
        self.assertTrue(len(results["nba"]["error"]) > 0)

    @patch.dict(os.environ, {"SHIPP_API_KEY": "test-key"}, clear=False)
    @patch.object(requests.Session, "request")
    def test_close_all(self, mock_request):
        """close_all closes all connections and clears the dict."""
        mock_request.return_value = self._make_ok_response(
            {"connection_id": "conn-nba"}
        )
        manager = ShippManager()
        manager.connect("nba")
        mock_request.return_value = self._make_ok_response({})
        manager.close_all()
        self.assertEqual(len(manager.connections), 0)

    @patch.dict(os.environ, {"SHIPP_API_KEY": "test-key"}, clear=False)
    @patch.object(requests.Session, "request")
    def test_connected_sports(self, mock_request):
        """connected_sports lists all active sport keys."""
        create_nba = self._make_ok_response({"connection_id": "c1"})
        create_mlb = self._make_ok_response({"connection_id": "c2"})
        mock_request.side_effect = [create_nba, create_mlb]

        manager = ShippManager()
        manager.connect("nba")
        manager.connect("mlb")

        sports = manager.connected_sports()
        self.assertIn("nba", sports)
        self.assertIn("mlb", sports)
        self.assertEqual(len(sports), 2)


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestHelpers(unittest.TestCase):
    """Tests for _safe_int and _format_start_time."""

    def test_safe_int_normal(self):
        self.assertEqual(_safe_int(42), 42)

    def test_safe_int_string(self):
        self.assertEqual(_safe_int("7"), 7)

    def test_safe_int_none(self):
        self.assertEqual(_safe_int(None), 0)

    def test_safe_int_bad_string(self):
        self.assertEqual(_safe_int("abc"), 0)

    def test_format_start_time_iso(self):
        """ISO timestamp with Z is formatted to local time."""
        result = _format_start_time("2026-02-18T19:30:00Z")
        # Should contain colon (time) and AM/PM
        self.assertIn(":", result)

    def test_format_start_time_invalid(self):
        """Invalid timestamp returns the raw string."""
        result = _format_start_time("not-a-date")
        self.assertEqual(result, "not-a-date")


if __name__ == "__main__":
    unittest.main()
