#!/usr/bin/env python3
"""
Game Day Dashboard — Browser Version

Flask app that serves a live-updating sports dashboard.
Uses Server-Sent Events (SSE) to push updates to the browser.

Usage:
    python web_dashboard.py <SHIPP_API_KEY> [--sports soccer] [--port 5050]
    Then open http://localhost:5050 in your browser.
"""

import argparse
import json
import logging
import os
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime

from flask import Flask, Response, jsonify, render_template_string

from .shipp_wrapper import ShippManager, ShippConnectionError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global state (shared between background poller and request handlers)
# ---------------------------------------------------------------------------

all_games: dict[str, dict] = defaultdict(dict)  # sport -> {game_id -> game_dict}
connection_status: dict[str, str] = {}  # sport -> "connected" | "error: ..."
last_poll_time: float = 0
poll_count: int = 0
manager: ShippManager = None

SPORT_LABELS = {"nba": "NBA", "mlb": "MLB (Spring Training)", "soccer": "Soccer"}
SPORT_COLORS = {"nba": "#ff4444", "mlb": "#4488ff", "soccer": "#44cc44"}
DEFAULT_SPORTS = ["nba", "mlb", "soccer"]


def game_state_to_dict(sport: str, game_id: str, event: dict) -> dict:
    """Convert a raw Shipp event into a normalized game dict."""
    home = event.get("home_name") or event.get("home_team") or event.get("home") or ""
    away = event.get("away_name") or event.get("away_team") or event.get("away") or ""

    home_score = event.get("home_points") or event.get("home_score") or 0
    away_score = event.get("away_points") or event.get("away_score") or 0
    try:
        home_score = int(home_score)
    except (ValueError, TypeError):
        home_score = 0
    try:
        away_score = int(away_score)
    except (ValueError, TypeError):
        away_score = 0

    raw_status = str(event.get("game_status") or event.get("status") or "scheduled").lower()
    if raw_status in ("live", "in_progress", "active", "in progress"):
        status = "live"
    elif raw_status in ("final", "finished", "completed", "closed"):
        status = "final"
    else:
        status = "scheduled"

    period = event.get("game_period") or event.get("period") or event.get("inning") or ""
    clock = event.get("clock") or event.get("time") or ""
    minute = event.get("minute") or ""

    display_status = ""
    if status == "final":
        display_status = "FINAL"
    elif status == "live":
        if sport == "soccer" and minute:
            display_status = f"{minute}'"
        elif sport == "nba" and period:
            try:
                q = int(period)
                display_status = f"Q{q}" if q <= 4 else f"OT{q - 4}"
            except (ValueError, TypeError):
                display_status = str(period)
            if clock:
                display_status += f" {clock}"
        elif sport == "mlb":
            half = event.get("half") or event.get("inning_half") or ""
            if period:
                prefix = "Top" if str(half).lower() in ("top", "t") else "Bot"
                display_status = f"{prefix} {period}"
            outs = event.get("outs")
            if outs is not None:
                display_status += f" {outs} out{'s' if int(outs) != 1 else ''}"
        else:
            display_status = "LIVE"
    else:
        sched = event.get("scheduled") or event.get("start_time") or ""
        if sched:
            try:
                dt = datetime.fromisoformat(sched.replace("Z", "+00:00"))
                local = dt.astimezone()
                display_status = local.strftime("%b %d %I:%M %p")
            except (ValueError, TypeError):
                display_status = str(sched)
        else:
            display_status = "SCHED"

    desc = event.get("desc") or event.get("description") or event.get("text") or ""

    return {
        "game_id": game_id,
        "sport": sport,
        "home_team": home,
        "away_team": away,
        "home_score": home_score,
        "away_score": away_score,
        "status": status,
        "display_status": display_status,
        "last_play": str(desc)[:80] if desc else "",
    }


# ---------------------------------------------------------------------------
# Background poller
# ---------------------------------------------------------------------------

def poll_loop(sports: list[str], interval: int = 10):
    """Background thread that polls Shipp and updates global state."""
    global last_poll_time, poll_count, manager

    # Connect to each sport
    for sport in sports:
        try:
            cid = manager.connect(sport)
            connection_status[sport] = f"connected ({cid[:12]}...)"
            logger.info("Connected %s: %s", sport, cid)
        except ShippConnectionError as exc:
            connection_status[sport] = f"error: {exc}"
            logger.error("Failed to connect %s: %s", sport, exc)

    while True:
        try:
            poll_results = manager.poll_all()
            last_poll_time = time.time()
            poll_count += 1

            for sport_key, data in poll_results.items():
                sport = sport_key.split(":")[0]

                if "error" in data and data.get("error"):
                    connection_status[sport] = f"poll error: {data['error'][:60]}"
                    continue

                events = data.get("data", [])
                for event in events:
                    if not isinstance(event, dict):
                        continue
                    game_id = str(
                        event.get("game_id") or event.get("id") or "unknown"
                    )
                    game = game_state_to_dict(sport, game_id, event)

                    # Preserve previous plays
                    existing = all_games[sport].get(game_id, {})
                    plays = existing.get("plays", [])
                    if game["last_play"] and (not plays or plays[-1] != game["last_play"]):
                        plays.append(game["last_play"])
                        plays = plays[-3:]  # keep last 3
                    game["plays"] = plays
                    game["last_play"] = plays[-1] if plays else ""

                    # Only update team names if we got non-empty values
                    if not game["home_team"] and existing.get("home_team"):
                        game["home_team"] = existing["home_team"]
                    if not game["away_team"] and existing.get("away_team"):
                        game["away_team"] = existing["away_team"]

                    all_games[sport][game_id] = game

        except Exception as exc:
            logger.error("Poll loop error: %s", exc)

        time.sleep(interval)


def get_dashboard_data() -> dict:
    """Snapshot of current state as a serializable dict."""
    now = datetime.now().strftime("%b %d, %Y  %I:%M:%S %p")

    sports_data = {}
    total_live = 0
    total_games = 0

    for sport in ["nba", "mlb", "soccer"]:
        games = list(all_games.get(sport, {}).values())
        if not games:
            continue

        # Sort: live first, then scheduled, then final
        games.sort(key=lambda g: (
            0 if g["status"] == "live" else 1 if g["status"] == "scheduled" else 2
        ))

        sports_data[sport] = {
            "label": SPORT_LABELS.get(sport, sport.upper()),
            "color": SPORT_COLORS.get(sport, "#ffffff"),
            "games": games,
        }
        total_games += len(games)
        total_live += sum(1 for g in games if g["status"] == "live")

    return {
        "timestamp": now,
        "total_live": total_live,
        "total_games": total_games,
        "poll_count": poll_count,
        "sports": sports_data,
        "connections": connection_status,
    }


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__)


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/status")
def api_status():
    return jsonify(get_dashboard_data())


@app.route("/api/stream")
def api_stream():
    def generate():
        while True:
            data = get_dashboard_data()
            yield f"data: {json.dumps(data)}\n\n"
            time.sleep(5)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# HTML Template
# ---------------------------------------------------------------------------

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Game Day Dashboard</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    background: #0d1117;
    color: #e6edf3;
    font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
    min-height: 100vh;
    padding: 20px;
  }

  .container {
    max-width: 960px;
    margin: 0 auto;
  }

  .header {
    text-align: center;
    padding: 24px 0 16px;
    border-bottom: 1px solid #30363d;
    margin-bottom: 24px;
  }

  .header h1 {
    font-size: 28px;
    font-weight: 700;
    letter-spacing: 2px;
    color: #ffffff;
  }

  .header .meta {
    color: #8b949e;
    font-size: 14px;
    margin-top: 8px;
  }

  .header .live-badge {
    display: inline-block;
    background: #da3633;
    color: white;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
    margin-left: 8px;
    animation: pulse 2s infinite;
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.6; }
  }

  .sport-section {
    margin-bottom: 28px;
  }

  .sport-header {
    font-size: 16px;
    font-weight: 700;
    padding: 8px 16px;
    border-left: 4px solid;
    margin-bottom: 12px;
    text-transform: uppercase;
    letter-spacing: 1px;
  }

  .game-card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 14px 18px;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 16px;
    transition: border-color 0.3s;
  }

  .game-card:hover {
    border-color: #484f58;
  }

  .game-card.live {
    border-left: 3px solid #3fb950;
  }

  .game-card.final {
    opacity: 0.6;
  }

  .game-card.scheduled {
    border-left: 3px solid #d29922;
  }

  .teams {
    flex: 1;
    min-width: 0;
  }

  .team-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 2px 0;
  }

  .team-name {
    flex: 1;
    font-size: 15px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .score {
    font-size: 20px;
    font-weight: 700;
    min-width: 32px;
    text-align: right;
    font-variant-numeric: tabular-nums;
  }

  .live .score { color: #ffffff; }
  .final .score { color: #8b949e; }
  .scheduled .score { color: #484f58; }

  .status-badge {
    min-width: 100px;
    text-align: center;
    padding: 6px 12px;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 600;
    white-space: nowrap;
  }

  .status-live {
    background: rgba(63, 185, 80, 0.15);
    color: #3fb950;
  }

  .status-final {
    background: rgba(139, 148, 158, 0.1);
    color: #8b949e;
  }

  .status-scheduled {
    background: rgba(210, 153, 34, 0.1);
    color: #d29922;
  }

  .last-play {
    flex: 1;
    font-size: 12px;
    color: #8b949e;
    font-style: italic;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 280px;
  }

  .no-games {
    text-align: center;
    color: #8b949e;
    padding: 40px;
    font-size: 16px;
  }

  .footer {
    text-align: center;
    padding: 20px 0;
    color: #484f58;
    font-size: 12px;
    border-top: 1px solid #21262d;
    margin-top: 24px;
  }

  .footer a {
    color: #58a6ff;
    text-decoration: none;
  }

  .connection-bar {
    display: flex;
    justify-content: center;
    gap: 16px;
    margin-bottom: 20px;
    font-size: 12px;
  }

  .conn-item {
    display: flex;
    align-items: center;
    gap: 6px;
    color: #8b949e;
  }

  .conn-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    display: inline-block;
  }

  .conn-dot.ok { background: #3fb950; }
  .conn-dot.err { background: #da3633; }
  .conn-dot.pending { background: #d29922; }

  .update-flash {
    animation: flash 0.5s ease-out;
  }

  @keyframes flash {
    0% { background: rgba(63, 185, 80, 0.1); }
    100% { background: transparent; }
  }

  @media (max-width: 640px) {
    body { padding: 10px; }
    .game-card { flex-wrap: wrap; gap: 8px; }
    .last-play { max-width: 100%; flex-basis: 100%; }
    .status-badge { min-width: auto; }
  }
</style>
</head>
<body>

<div class="container">
  <div class="header">
    <h1>GAME DAY DASHBOARD</h1>
    <div class="meta">
      <span id="timestamp">Loading...</span>
      <span id="live-indicator"></span>
    </div>
  </div>

  <div class="connection-bar" id="connections"></div>

  <div id="dashboard">
    <div class="no-games">Connecting to live data feeds...</div>
  </div>

  <div class="footer">
    Powered by <a href="https://shipp.ai" target="_blank">Shipp.ai</a> &middot;
    Auto-updates every 5s &middot;
    Poll #<span id="poll-count">0</span>
  </div>
</div>

<script>
const SPORT_ORDER = ['nba', 'mlb', 'soccer'];

function renderDashboard(data) {
  // Header
  document.getElementById('timestamp').textContent = data.timestamp;
  document.getElementById('poll-count').textContent = data.poll_count;

  const indicator = document.getElementById('live-indicator');
  if (data.total_live > 0) {
    indicator.innerHTML = `<span class="live-badge">${data.total_live} LIVE</span>`;
  } else {
    indicator.innerHTML = `<span style="color:#8b949e; margin-left:8px">${data.total_games} games tracked</span>`;
  }

  // Connections
  const connBar = document.getElementById('connections');
  let connHtml = '';
  for (const [sport, status] of Object.entries(data.connections || {})) {
    const isOk = status.startsWith('connected');
    const dotClass = isOk ? 'ok' : 'err';
    const label = sport.toUpperCase();
    connHtml += `<div class="conn-item"><span class="conn-dot ${dotClass}"></span>${label}</div>`;
  }
  connBar.innerHTML = connHtml;

  // Sports
  const container = document.getElementById('dashboard');
  const sportKeys = SPORT_ORDER.filter(s => data.sports[s]);

  if (sportKeys.length === 0) {
    container.innerHTML = '<div class="no-games">No games found. Waiting for data...</div>';
    return;
  }

  let html = '';
  for (const sport of sportKeys) {
    const info = data.sports[sport];
    html += `<div class="sport-section">`;
    html += `<div class="sport-header" style="border-color: ${info.color}; color: ${info.color}">${info.label}</div>`;

    for (const game of info.games) {
      const statusClass = game.status;
      let statusBadgeClass = 'status-scheduled';
      if (game.status === 'live') statusBadgeClass = 'status-live';
      else if (game.status === 'final') statusBadgeClass = 'status-final';

      const homeScore = game.status === 'scheduled' ? '' : game.home_score;
      const awayScore = game.status === 'scheduled' ? '' : game.away_score;
      const vs = game.status === 'scheduled' ? 'vs' : '';

      html += `
        <div class="game-card ${statusClass}" id="game-${game.game_id}">
          <div class="teams">
            <div class="team-row">
              <span class="team-name">${escHtml(game.away_team || 'TBD')}</span>
              <span class="score">${awayScore}</span>
            </div>
            <div class="team-row">
              <span class="team-name">${escHtml(game.home_team || 'TBD')}</span>
              <span class="score">${homeScore}</span>
            </div>
          </div>
          <div class="status-badge ${statusBadgeClass}">${escHtml(game.display_status)}</div>
          ${game.last_play ? `<div class="last-play">${escHtml(game.last_play)}</div>` : ''}
        </div>`;
    }
    html += '</div>';
  }

  container.innerHTML = html;
}

function escHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// SSE connection
let evtSource = null;

function connect() {
  evtSource = new EventSource('/api/stream');

  evtSource.onmessage = function(event) {
    try {
      const data = JSON.parse(event.data);
      renderDashboard(data);
    } catch (e) {
      console.error('Parse error:', e);
    }
  };

  evtSource.onerror = function() {
    console.log('SSE disconnected, reconnecting in 3s...');
    evtSource.close();
    setTimeout(connect, 3000);
  };
}

// Initial load via fetch, then switch to SSE
fetch('/api/status')
  .then(r => r.json())
  .then(data => renderDashboard(data))
  .catch(() => {});

connect();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Game Day Dashboard — Browser Version")
    parser.add_argument("api_key", nargs="?", default="",
                        help="Shipp API key (or set SHIPP_API_KEY env var)")
    parser.add_argument("--sports", type=str, default=",".join(DEFAULT_SPORTS),
                        help="Comma-separated sports (default: nba,mlb,soccer)")
    parser.add_argument("--port", type=int, default=5050, help="Port (default: 5050)")
    parser.add_argument("--interval", type=int, default=10,
                        help="Poll interval in seconds (default: 10)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    api_key = args.api_key or os.environ.get("SHIPP_API_KEY", "")
    if not api_key:
        print("Error: Provide API key as argument or set SHIPP_API_KEY env var")
        print("Usage: python web_dashboard.py <YOUR_API_KEY>")
        sys.exit(1)

    os.environ["SHIPP_API_KEY"] = api_key

    global manager
    try:
        manager = ShippManager(api_key=api_key)
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(1)

    sports = [s.strip().lower() for s in args.sports.split(",") if s.strip()]

    print(f"\n  Game Day Dashboard — Browser Version")
    print(f"  Sports: {', '.join(sports)}")
    print(f"  Poll interval: {args.interval}s")
    print(f"  Server: http://localhost:{args.port}")
    print(f"\n  Open your browser to http://localhost:{args.port}\n")

    # Start background poller
    poller = threading.Thread(
        target=poll_loop,
        args=(sports, args.interval),
        daemon=True,
    )
    poller.start()

    # Start Flask
    app.run(host="0.0.0.0", port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
