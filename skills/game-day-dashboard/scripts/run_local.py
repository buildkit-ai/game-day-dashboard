#!/usr/bin/env python3
"""
Run the Game Day Dashboard locally for a few poll cycles.
Same as dashboard.py but prints frames inline (no alternate screen buffer).
"""
import os
import sys
import time
import signal
import logging
from collections import defaultdict

os.environ["SHIPP_API_KEY"] = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SHIPP_API_KEY", "")

from rich.console import Console
from rich.live import Live

from shipp_wrapper import ShippManager, ShippConnectionError
from dashboard import (
    parse_game_data,
    parse_events,
    build_dashboard,
    SPORT_LABELS,
    DEFAULT_SPORTS,
)

console = Console(width=120)
MAX_CYCLES = 3
INTERVAL = 12
# Only connect to sports with active live data
SPORTS_TO_TRACK = sys.argv[2].split(",") if len(sys.argv) > 2 else DEFAULT_SPORTS


def main():
    logging.basicConfig(level=logging.WARNING)

    console.print("\n[bold cyan]Game Day Dashboard — Live Mode[/bold cyan]")
    console.print("[dim]Will run for 5 poll cycles then exit.[/dim]\n")

    try:
        manager = ShippManager()
    except ValueError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        sys.exit(1)

    # Connect to each sport
    connected = []
    for sport in SPORTS_TO_TRACK:
        try:
            cid = manager.connect(sport)
            connected.append(sport)
            console.print(f"  [green]Connected:[/green] {SPORT_LABELS.get(sport, sport)} → {cid}")
        except ShippConnectionError as exc:
            console.print(f"  [red]Failed:[/red] {SPORT_LABELS.get(sport, sport)} → {exc}")

    if not connected:
        console.print("\n[bold red]No connections. Exiting.[/bold red]")
        sys.exit(1)

    console.print(f"\n[dim]Polling every {INTERVAL}s for {MAX_CYCLES} cycles. Ctrl+C to stop early.[/dim]\n")

    all_games = defaultdict(dict)
    shutdown = False

    def handle_signal(signum, frame):
        nonlocal shutdown
        shutdown = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        with Live(
            build_dashboard(all_games, live_only=False),
            console=console,
            refresh_per_second=1,
            screen=False,
        ) as live:
            for cycle in range(MAX_CYCLES):
                if shutdown:
                    break

                poll_results = manager.poll_all()

                for sport_key, data in poll_results.items():
                    sport = sport_key.split(":")[0]

                    if "error" in data and data.get("error"):
                        continue

                    # Process events from data[] array
                    events = data.get("data", [])
                    for event in events:
                        if not isinstance(event, dict):
                            continue

                        game_id = str(
                            event.get("game_id")
                            or event.get("id")
                            or "unknown"
                        )

                        # Build/update game state from event
                        if game_id not in all_games[sport]:
                            from dashboard import GameState
                            gs = GameState(game_id, sport)
                            all_games[sport][game_id] = gs

                        gs = all_games[sport][game_id]

                        # Update fields defensively
                        home = event.get("home_name") or event.get("home_team") or event.get("home") or ""
                        away = event.get("away_name") or event.get("away_team") or event.get("away") or ""
                        if home:
                            gs.home_team = home
                        if away:
                            gs.away_team = away

                        home_score = event.get("home_points") or event.get("home_score")
                        away_score = event.get("away_points") or event.get("away_score")
                        if home_score is not None:
                            try:
                                gs.home_score = int(home_score)
                            except (ValueError, TypeError):
                                pass
                        if away_score is not None:
                            try:
                                gs.away_score = int(away_score)
                            except (ValueError, TypeError):
                                pass

                        status = str(event.get("game_status") or event.get("status") or "").lower()
                        if status in ("live", "in_progress", "active", "in progress"):
                            gs.status = "live"
                        elif status in ("final", "finished", "completed", "closed"):
                            gs.status = "final"
                        elif status in ("scheduled",):
                            gs.status = "scheduled"

                        period = event.get("game_period") or event.get("period") or event.get("inning")
                        if period:
                            gs.period = str(period)
                        clock = event.get("clock") or event.get("time") or event.get("minute")
                        if clock:
                            if sport == "soccer":
                                gs.period = f"{clock}'"
                            else:
                                gs.clock = str(clock)

                        desc = event.get("desc") or event.get("description") or event.get("text")
                        if desc:
                            gs.add_play(str(desc))

                        start = event.get("scheduled") or event.get("start_time")
                        if start and gs.status == "scheduled":
                            from dashboard import _format_start_time
                            gs.start_time = _format_start_time(start)

                live.update(build_dashboard(all_games, live_only=False))

                # Wait
                elapsed = 0.0
                while elapsed < INTERVAL and not shutdown:
                    time.sleep(0.5)
                    elapsed += 0.5

    finally:
        console.print("\n[dim]Shutting down...[/dim]")
        manager.close_all()

    # Print final summary
    total_games = sum(len(g) for g in all_games.values())
    total_live = sum(1 for sg in all_games.values() for g in sg.values() if g.status == "live")
    console.print(f"\n[bold]Session complete:[/bold] {total_games} games tracked, {total_live} live")
    console.print("[dim]Connections closed.[/dim]\n")


if __name__ == "__main__":
    main()
