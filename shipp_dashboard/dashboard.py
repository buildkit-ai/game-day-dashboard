#!/usr/bin/env python3
"""
Game Day Dashboard — Full-screen live sports scoreboard.

Tracks NBA, MLB, and Soccer games in real time with scores and play-by-play.
Designed for sports bars, watch parties, and personal game day setups.

Usage:
    python dashboard.py
    python dashboard.py --sports nba,soccer
    python dashboard.py --interval 15
    python dashboard.py --live-only
"""

import argparse
import signal
import sys
import time
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

try:
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except ImportError:
    print("Error: 'rich' library is required.")
    print("Install it with: pip install rich")
    sys.exit(1)

from .shipp_wrapper import ShippManager, ShippConnectionError

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_SPORTS = ["nba", "mlb", "soccer"]
DEFAULT_INTERVAL = 10  # seconds
MAX_PLAYS_PER_GAME = 3  # most recent plays to display per game

logger = logging.getLogger("dashboard")

# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


class GameState:
    """Tracks the current state of a single game."""

    def __init__(self, game_id: str, sport: str):
        self.game_id = game_id
        self.sport = sport
        self.home_team = "HOME"
        self.away_team = "AWAY"
        self.home_score = 0
        self.away_score = 0
        self.status = "scheduled"  # scheduled, live, final
        self.period = ""  # Q1, Top 5th, 45', etc.
        self.clock = ""  # 4:32, 2 outs, etc.
        self.start_time: Optional[str] = None
        self.recent_plays: list[str] = []

    @property
    def display_status(self) -> str:
        if self.status == "final":
            return "FINAL"
        if self.status == "scheduled":
            return self.start_time or "SCHED"
        # Live game — show period and clock
        parts = [p for p in [self.period, self.clock] if p]
        return "  ".join(parts) if parts else "LIVE"

    @property
    def score_line(self) -> str:
        return f"{self.away_team} {self.away_score} - {self.home_score} {self.home_team}"

    def add_play(self, description: str):
        self.recent_plays.append(description)
        if len(self.recent_plays) > MAX_PLAYS_PER_GAME:
            self.recent_plays = self.recent_plays[-MAX_PLAYS_PER_GAME:]


# ---------------------------------------------------------------------------
# Event Parsing
# ---------------------------------------------------------------------------


def parse_game_data(game: dict, sport: str) -> GameState:
    """Parse a game object from Shipp into a GameState."""
    game_id = str(
        game.get("game_id")
        or game.get("id")
        or game.get("gameId")
        or "unknown"
    )
    state = GameState(game_id, sport)

    # Teams — handle nested objects or flat strings
    home = game.get("home_team") or game.get("home") or {}
    away = game.get("away_team") or game.get("away") or {}
    if isinstance(home, dict):
        state.home_team = (
            home.get("abbreviation")
            or home.get("abbrev")
            or home.get("name", "HOME")
        )
    else:
        state.home_team = str(home)

    if isinstance(away, dict):
        state.away_team = (
            away.get("abbreviation")
            or away.get("abbrev")
            or away.get("name", "AWAY")
        )
    else:
        state.away_team = str(away)

    # Scores
    state.home_score = _safe_int(
        game.get("home_score") or game.get("homeScore") or 0
    )
    state.away_score = _safe_int(
        game.get("away_score") or game.get("awayScore") or 0
    )

    # Status
    raw_status = str(
        game.get("status") or game.get("state") or "scheduled"
    ).lower()
    if raw_status in ("live", "in_progress", "active", "in progress"):
        state.status = "live"
    elif raw_status in ("final", "finished", "completed", "closed"):
        state.status = "final"
    else:
        state.status = "scheduled"

    # Period / clock — sport-specific
    state.period = str(game.get("period") or game.get("inning") or "")
    state.clock = str(game.get("clock") or game.get("time") or "")

    # Format period display based on sport
    if sport == "nba" and state.period:
        try:
            q = int(state.period)
            if q <= 4:
                state.period = f"Q{q}"
            else:
                state.period = f"OT{q - 4}"
        except (ValueError, TypeError):
            pass

    if sport == "mlb":
        half = game.get("half") or game.get("inning_half") or ""
        inning = game.get("inning") or game.get("period") or ""
        if inning:
            prefix = "Top" if str(half).lower() in ("top", "t") else "Bot"
            state.period = f"{prefix} {inning}"
        outs = game.get("outs")
        if outs is not None:
            state.clock = f"{outs} out{'s' if int(outs) != 1 else ''}"

    if sport == "soccer":
        minute = game.get("minute") or game.get("clock") or ""
        if minute:
            state.period = f"{minute}'"

    # Start time for scheduled games
    start = game.get("start_time") or game.get("startTime") or game.get("scheduled")
    if start:
        state.start_time = _format_start_time(start)

    return state


def parse_events(events: list[dict], games: dict[str, GameState], sport: str):
    """
    Process play-by-play events and update game states.
    Modifies games dict in place.
    """
    for event in events:
        game_id = str(
            event.get("game_id")
            or event.get("gameId")
            or event.get("id")
            or ""
        )

        # Update score if present in event
        if game_id in games:
            game = games[game_id]

            home_score = event.get("home_score") or event.get("homeScore")
            away_score = event.get("away_score") or event.get("awayScore")
            if home_score is not None:
                game.home_score = _safe_int(home_score)
            if away_score is not None:
                game.away_score = _safe_int(away_score)

            # Update period/clock from event
            period = event.get("period") or event.get("inning")
            if period:
                game.period = str(period)
            clock = event.get("clock") or event.get("time")
            if clock:
                game.clock = str(clock)

            status = str(event.get("status") or "").lower()
            if status in ("final", "finished", "completed"):
                game.status = "final"
            elif status in ("live", "in_progress", "active"):
                game.status = "live"

        # Extract play description
        description = (
            event.get("description")
            or event.get("text")
            or event.get("play")
            or event.get("detail")
        )
        if description and game_id in games:
            games[game_id].add_play(str(description))


# ---------------------------------------------------------------------------
# Display Rendering
# ---------------------------------------------------------------------------

SPORT_LABELS = {
    "nba": "NBA",
    "mlb": "MLB (Spring Training)",
    "soccer": "Soccer",
}

SPORT_STYLES = {
    "nba": "bright_red",
    "mlb": "bright_blue",
    "soccer": "bright_green",
}


def build_dashboard(
    all_games: dict[str, dict[str, GameState]],
    live_only: bool = False,
) -> Panel:
    """Build the full dashboard panel from current game states."""
    now = datetime.now().strftime("%b %d, %Y  %I:%M %p")

    total_live = sum(
        1
        for sport_games in all_games.values()
        for g in sport_games.values()
        if g.status == "live"
    )
    total_games = sum(len(sg) for sg in all_games.values())

    header_text = Text()
    header_text.append("GAME DAY DASHBOARD\n", style="bold white")
    header_text.append(f"{now}", style="dim")
    header_text.append(f"   {total_live} live / {total_games} total", style="dim cyan")

    sections = [header_text, Text("")]

    for sport in ["nba", "mlb", "soccer"]:
        games = all_games.get(sport, {})
        if not games:
            continue

        filtered = games
        if live_only:
            filtered = {
                gid: g for gid, g in games.items() if g.status == "live"
            }
            if not filtered:
                continue

        label = SPORT_LABELS.get(sport, sport.upper())
        style = SPORT_STYLES.get(sport, "white")

        section_header = Text(f"  {label}", style=f"bold {style}")
        sections.append(section_header)

        table = Table(
            show_header=False,
            show_edge=False,
            pad_edge=False,
            box=None,
            padding=(0, 2),
        )
        table.add_column("game", min_width=35, no_wrap=True)
        table.add_column("status", min_width=18, no_wrap=True)
        table.add_column("play", min_width=45)

        for game in sorted(
            filtered.values(),
            key=lambda g: (
                0 if g.status == "live" else 1 if g.status == "scheduled" else 2
            ),
        ):
            score_text = Text(game.score_line)
            if game.status == "live":
                score_text.stylize("bold white")
            elif game.status == "final":
                score_text.stylize("dim")

            status_text = Text(game.display_status)
            if game.status == "live":
                status_text.stylize("bold green")
            elif game.status == "final":
                status_text.stylize("dim red")
            else:
                status_text.stylize("dim yellow")

            last_play = ""
            if game.recent_plays:
                last_play = game.recent_plays[-1]
                if len(last_play) > 50:
                    last_play = last_play[:47] + "..."

            play_text = Text(f"> {last_play}" if last_play else "")
            play_text.stylize("italic dim")

            table.add_row(score_text, status_text, play_text)

        sections.append(table)
        sections.append(Text(""))

    if not any(all_games.get(s) for s in ["nba", "mlb", "soccer"]):
        no_games = Text(
            "\n  No games found for today. Check back later!\n",
            style="dim yellow",
        )
        sections.append(no_games)

    # Build final layout as a group
    from rich.console import Group
    content = Group(*sections)

    return Panel(
        content,
        title="[bold white]LIVE[/bold white]",
        subtitle="[dim]Ctrl+C to exit  |  Refreshes automatically[/dim]",
        border_style="bright_cyan",
        expand=True,
    )


# ---------------------------------------------------------------------------
# Main Loop
# ---------------------------------------------------------------------------


def run_dashboard(
    sports: list[str],
    interval: int = DEFAULT_INTERVAL,
    live_only: bool = False,
):
    """Main dashboard loop — connect, poll, render, repeat."""
    console = Console()

    console.print(
        "\n[bold cyan]Starting Game Day Dashboard...[/bold cyan]\n"
    )

    # Initialize Shipp connections
    try:
        manager = ShippManager()
    except ValueError as exc:
        console.print(f"[bold red]Configuration error:[/bold red] {exc}")
        console.print(
            "\nSet your API key: export SHIPP_API_KEY='your-key-here'"
        )
        console.print(
            "Get a free key at: https://platform.shipp.ai\n"
        )
        sys.exit(1)

    # Create connections for requested sports
    connected = []
    for sport in sports:
        sport = sport.strip().lower()
        if sport not in ShippManager.SPORT_CONFIG:
            console.print(
                f"[yellow]Warning: Unknown sport '{sport}', skipping[/yellow]"
            )
            continue
        try:
            manager.connect(sport)
            connected.append(sport)
            console.print(
                f"  [green]Connected:[/green] {SPORT_LABELS.get(sport, sport)}"
            )
        except ShippConnectionError as exc:
            console.print(
                f"  [red]Failed to connect {sport}:[/red] {exc}"
            )

    if not connected:
        console.print(
            "\n[bold red]No sports connections established. Exiting.[/bold red]"
        )
        sys.exit(1)

    console.print(
        f"\n[dim]Polling every {interval}s. Press Ctrl+C to stop.[/dim]\n"
    )

    # Track all game states across sports
    all_games: dict[str, dict[str, GameState]] = defaultdict(dict)

    # Graceful shutdown
    shutdown = False

    def handle_signal(signum, frame):
        nonlocal shutdown
        shutdown = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        with Live(
            build_dashboard(all_games, live_only),
            console=console,
            refresh_per_second=1,
            screen=True,
        ) as live:
            while not shutdown:
                # Poll all connections
                poll_results = manager.poll_all()

                for sport_key, data in poll_results.items():
                    # Extract base sport name (handle "soccer:premier_league")
                    sport = sport_key.split(":")[0]

                    if "error" in data and data["error"]:
                        logger.warning(
                            "Error polling %s: %s", sport_key, data["error"]
                        )
                        continue

                    # Process games from response
                    games_list = (
                        data.get("games")
                        or data.get("scoreboard")
                        or data.get("matches")
                        or []
                    )
                    for game_data in games_list:
                        state = parse_game_data(game_data, sport)
                        # Preserve existing plays if game already tracked
                        existing = all_games[sport].get(state.game_id)
                        if existing:
                            state.recent_plays = existing.recent_plays
                        all_games[sport][state.game_id] = state

                    # Process play-by-play events
                    events = data.get("events") or data.get("plays") or []
                    parse_events(events, all_games[sport], sport)

                # Update the live display
                live.update(build_dashboard(all_games, live_only))

                # Wait for next poll
                elapsed = 0.0
                while elapsed < interval and not shutdown:
                    time.sleep(0.5)
                    elapsed += 0.5

    finally:
        console.print("\n[dim]Shutting down connections...[/dim]")
        manager.close_all()
        console.print("[green]Dashboard stopped cleanly.[/green]\n")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_int(value) -> int:
    """Safely convert a value to int, defaulting to 0."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def _format_start_time(raw: str) -> str:
    """Format an ISO timestamp into a human-readable start time."""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        local = dt.astimezone()
        return local.strftime("%I:%M %p")
    except (ValueError, TypeError):
        return str(raw)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Game Day Dashboard — live sports scoreboard"
    )
    parser.add_argument(
        "--sports",
        type=str,
        default=",".join(DEFAULT_SPORTS),
        help="Comma-separated sports to track (default: nba,mlb,soccer)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL,
        help=f"Poll interval in seconds (default: {DEFAULT_INTERVAL})",
    )
    parser.add_argument(
        "--live-only",
        action="store_true",
        help="Only show games currently in progress",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    sports = [s.strip().lower() for s in args.sports.split(",") if s.strip()]

    run_dashboard(
        sports=sports,
        interval=args.interval,
        live_only=args.live_only,
    )


if __name__ == "__main__":
    main()
