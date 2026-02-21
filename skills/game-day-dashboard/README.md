# Game Day Dashboard

**Your personal sports command center.** Track every live game across NBA, MLB, and Soccer on a single screen with real-time scores and play-by-play.

---

## The Problem

You're hosting a watch party. Three NBA games, a Champions League match, and spring training all happening at once. You're flipping between apps, refreshing browser tabs, and still missing key plays. You need one screen that shows everything.

## The Solution

Game Day Dashboard is a terminal-based live scoreboard that fits on any display — from a laptop to a bar TV. It auto-detects today's games, tracks all of them simultaneously, and streams play-by-play as it happens.

```
+----------------------------------------------+
|          GAME DAY DASHBOARD                  |
|          Feb 18, 2026 — 8 games live         |
+----------------------------------------------+
|                                              |
|  NBA                                         |
|  ┌──────────────────────────────────────┐    |
|  │ LAL 87 - 82 BOS   Q3 4:32           │    |
|  │ > LeBron James 3-pointer (27 pts)    │    |
|  ├──────────────────────────────────────┤    |
|  │ MIA 64 - 71 GSW   Q2 1:15           │    |
|  │ > Curry pull-up jumper (18 pts)      │    |
|  └──────────────────────────────────────┘    |
|                                              |
|  SOCCER                                      |
|  ┌──────────────────────────────────────┐    |
|  │ Arsenal 2 - 1 Bayern   67'           │    |
|  │ > GOAL! Saka (Arsenal) 65'           │    |
|  └──────────────────────────────────────┘    |
|                                              |
|  MLB (Spring Training)                       |
|  ┌──────────────────────────────────────┐    |
|  │ NYY 3 - 1 BOS   Top 5th, 1 out      │    |
|  │ > Judge singles to right field       │    |
|  └──────────────────────────────────────┘    |
+----------------------------------------------+
```

## Features

- **Multi-sport, multi-game** — NBA, MLB, and Soccer on one screen
- **Real-time updates** — Scores refresh every 10 seconds
- **Play-by-play feed** — Key moments appear as they happen
- **Zero duplicates** — Cursor-based polling ensures no repeated events
- **Terminal-native** — Works over SSH, on any screen, no browser needed
- **Low bandwidth** — Only fetches new events, not full game state

## Quick Start

### 1. Install dependencies

```bash
pip install rich requests
```

### 2. Set your API key

```bash
export SHIPP_API_KEY="your-api-key-here"
```

### 3. Run the dashboard

```bash
python scripts/dashboard.py
```

### Optional flags

```bash
# Filter to specific sports
python scripts/dashboard.py --sports nba,soccer

# Adjust refresh interval (seconds)
python scripts/dashboard.py --interval 15

# Show only live games (hide scheduled/final)
python scripts/dashboard.py --live-only
```

## How It Works

1. On launch, the dashboard queries today's schedule for NBA, MLB, and Soccer
2. For each sport with active games, it creates a persistent data connection
3. Every 10 seconds (configurable), it polls each connection for new events
4. New scores and plays are rendered into the terminal grid
5. Finished games are marked FINAL; upcoming games show start times

## Requirements

| Dependency | Version | Purpose |
|------------|---------|---------|
| Python     | 3.9+    | Runtime |
| rich       | 13.0+   | Terminal UI rendering |
| requests   | 2.28+   | HTTP client |

## Configuration

| Environment Variable | Required | Description |
|---------------------|----------|-------------|
| `SHIPP_API_KEY`     | Yes      | API key for real-time sports data |

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "No games found" | Check that games are scheduled for today in your timezone |
| "Connection failed" | Verify your API key is set and valid |
| Scores not updating | Check your internet connection; the dashboard retries automatically |
| Display too wide | Shrink terminal font or maximize the window |

## License

MIT
