#!/usr/bin/env python3
"""
Game Day Dashboard — Single-shot runner.
Connects to real Shipp API, fetches schedules + live data, renders the dashboard.
"""
import os
import sys
import json
from collections import defaultdict
from datetime import datetime

os.environ["SHIPP_API_KEY"] = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SHIPP_API_KEY", "")

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from shipp_wrapper import ShippManager, ShippConnectionError

console = Console(width=120)

SPORT_LABELS = {"nba": "NBA", "mlb": "MLB (Spring Training)", "soccer": "Soccer"}
SPORT_STYLES = {"nba": "bright_red", "mlb": "bright_blue", "soccer": "bright_green"}


def main():
    console.print("\n[bold cyan]Game Day Dashboard[/bold cyan]")

    try:
        manager = ShippManager()
    except ValueError as exc:
        console.print(f"[bold red]Config error:[/bold red] {exc}")
        sys.exit(1)

    # ── Step 1: Fetch schedules (free, no credits) ──────────────────────
    console.print("[bold]Step 1:[/bold] Fetching schedules (free endpoint)\n")
    all_schedule_games = {}
    for sport in ["nba", "mlb", "soccer"]:
        label = SPORT_LABELS.get(sport, sport)
        console.print(f"  Fetching {label} schedule...", end=" ")
        games = manager.get_schedule(sport)
        all_schedule_games[sport] = games
        if games:
            console.print(f"[green]{len(games)} game(s) found[/green]")
        else:
            console.print("[yellow]no games / timed out[/yellow]")

    # ── Step 2: List existing connections ────────────────────────────────
    console.print(f"\n[bold]Step 2:[/bold] Checking existing connections\n")
    existing = manager.list_connections()
    for c in existing:
        cid = c.get("connection_id") or c.get("id")
        name = c.get("name", "unnamed")
        enabled = c.get("enabled", False)
        console.print(f"  [dim]{cid}[/dim] | {name} | enabled={enabled}")
    if not existing:
        console.print("  [dim]No existing connections[/dim]")

    # ── Step 3: Create or reuse connections ──────────────────────────────
    console.print(f"\n[bold]Step 3:[/bold] Creating connections for sports with games\n")
    for sport, games in all_schedule_games.items():
        if not games:
            console.print(f"  [dim]Skipping {sport} (no games)[/dim]")
            continue
        label = SPORT_LABELS.get(sport, sport)
        try:
            cid = manager.connect(sport)
            console.print(f"  [green]Connected:[/green] {label} → {cid}")
        except ShippConnectionError as exc:
            console.print(f"  [red]Failed:[/red] {label} → {exc}")

    # ── Step 4: Poll for live data ──────────────────────────────────────
    if manager.connected_sports():
        console.print(f"\n[bold]Step 4:[/bold] Polling connections for live data\n")
        poll_results = manager.poll_all()
        for sport_key, data in poll_results.items():
            if "error" in data and data.get("error"):
                console.print(f"  [yellow]{sport_key}:[/yellow] {data['error']}")
            else:
                events = data.get("data", [])
                console.print(f"  [cyan]{sport_key}:[/cyan] {len(events)} live event(s)")
                # Show first few events
                for ev in events[:3]:
                    desc = ev.get("desc") or ev.get("description") or ev.get("text") or json.dumps(ev)[:100]
                    console.print(f"    [dim]> {desc}[/dim]")
    else:
        console.print(f"\n[bold]Step 4:[/bold] [dim]No connections to poll[/dim]")
        poll_results = {}

    # ── Step 5: Render dashboard ────────────────────────────────────────
    console.print(f"\n[bold]Step 5:[/bold] Rendering dashboard\n")

    now = datetime.now().strftime("%b %d, %Y  %I:%M %p")
    sections = []

    header = Text()
    header.append("GAME DAY DASHBOARD\n", style="bold white")
    header.append(f"{now}", style="dim")
    sections.append(header)
    sections.append(Text(""))

    for sport in ["nba", "mlb", "soccer"]:
        games = all_schedule_games.get(sport, [])
        if not games:
            continue

        label = SPORT_LABELS.get(sport, sport)
        style = SPORT_STYLES.get(sport, "white")
        sections.append(Text(f"  {label}", style=f"bold {style}"))

        table = Table(show_header=False, show_edge=False, pad_edge=False, box=None, padding=(0, 2))
        table.add_column("game", min_width=40, no_wrap=True)
        table.add_column("status", min_width=18, no_wrap=True)
        table.add_column("info", min_width=30)

        for g in games[:8]:  # Show up to 8 games per sport
            home = g.get("home", g.get("home_team", "?"))
            away = g.get("away", g.get("away_team", "?"))
            status = g.get("game_status", g.get("status", "scheduled")).lower()
            home_score = g.get("home_score", g.get("homeScore", ""))
            away_score = g.get("away_score", g.get("awayScore", ""))

            # Score line
            if home_score or away_score:
                score_text = Text(f"{away} {away_score} - {home_score} {home}")
            else:
                score_text = Text(f"{away}  vs  {home}")

            if status in ("live", "in_progress", "active"):
                score_text.stylize("bold white")
            elif status in ("final", "finished", "completed"):
                score_text.stylize("dim")
            else:
                score_text.stylize("white")

            # Status
            if status in ("live", "in_progress", "active"):
                status_text = Text("LIVE", style="bold green")
            elif status in ("final", "finished", "completed"):
                status_text = Text("FINAL", style="dim red")
            else:
                sched = g.get("scheduled", g.get("start_time", ""))
                if sched:
                    try:
                        dt = datetime.fromisoformat(sched.replace("Z", "+00:00"))
                        local = dt.astimezone()
                        time_str = local.strftime("%b %d %I:%M %p")
                    except (ValueError, TypeError):
                        time_str = sched
                    status_text = Text(time_str, style="dim yellow")
                else:
                    status_text = Text("SCHED", style="dim yellow")

            # Game ID
            gid = g.get("game_id", g.get("id", ""))
            info_text = Text(f"id: {gid[:20]}..." if len(str(gid)) > 20 else f"id: {gid}", style="dim")

            table.add_row(score_text, status_text, info_text)

        sections.append(table)
        sections.append(Text(""))

    if not any(all_schedule_games.get(s) for s in ["nba", "mlb", "soccer"]):
        sections.append(Text("\n  No games found across any sport. Check back later!\n", style="dim yellow"))

    # Check for live events from polling
    total_live_events = 0
    for sport_key, data in poll_results.items():
        events = data.get("data", [])
        total_live_events += len(events)

    if total_live_events > 0:
        sections.append(Text(f"  Live events streaming: {total_live_events}", style="bold green"))
    else:
        sections.append(Text("  No live events right now — games may be scheduled for later", style="dim"))

    content = Group(*sections)
    panel = Panel(
        content,
        title="[bold white]LIVE[/bold white]",
        border_style="bright_cyan",
        expand=True,
    )
    console.print(panel)

    # Cleanup
    manager.close_all()
    console.print("\n[dim]Connections closed. Done.[/dim]\n")


if __name__ == "__main__":
    main()
