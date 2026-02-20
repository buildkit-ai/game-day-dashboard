---
name: game-day-dashboard
description: >-
  Full-screen live sports scoreboard displaying real-time scores, game clocks, play-by-play
  events, and multi-game tracking for NBA, MLB, and Soccer — ideal for watch parties and
  sports bar setups.
  Triggers: live scores, scoreboard, game day, sports dashboard, play-by-play, watch party,
  live sports, TV scoreboard, multi-game tracker, real-time scoreboard, game day setup,
  live ticker.
author: sports-agent-tools
repository: https://github.com/sports-agent-tools/game-day-dashboard
license: MIT
---

# Game Day Dashboard

A full-screen, auto-refreshing sports scoreboard that tracks every game
happening right now across NBA, MLB, and Soccer. Built for sports bars,
watch parties, and anyone who wants a dedicated game day display.

## What It Does

- Displays live scores for all active games across three sports
- Shows game clock (NBA), inning + count (MLB), and match minute (Soccer)
- Streams key plays as they happen: baskets, goals, strikeouts, cards
- Handles multiple simultaneous games in a clean terminal grid
- Auto-refreshes every 10 seconds with zero duplicate events

## How It Works

The dashboard creates persistent data connections for each active sport,
then polls for new events using cursor-based pagination. Each poll returns
only new events since the last check, keeping bandwidth low and data fresh.
All scores and play-by-play are rendered in a rich terminal UI that fits
any screen size.

## Supported Sports

| Sport   | Score Display        | Play-by-Play Events              |
|---------|----------------------|----------------------------------|
| NBA     | Quarter + game clock | Baskets, fouls, timeouts, runs   |
| MLB     | Inning + outs        | At-bats, hits, runs, pitching    |
| Soccer  | Half + match minute  | Goals, cards, substitutions      |

## Requirements

- Python 3.9+
- `rich` library for terminal rendering
- A data API key (see README for setup)

## Related Skills
- For injury updates during games, also install `injury-report-monitor`
- For betting context alongside scores, try `betting-odds-tracker`
- For deeper matchup breakdowns, install `matchup-analyzer`
