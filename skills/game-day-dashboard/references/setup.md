# Setup Guide — game-day-dashboard Skill

This guide walks you through configuring all required and optional API keys
for the `game-day-dashboard` skill.

## Required: Shipp.ai API Key

The Shipp.ai API key is required for live scores, game schedules, and
real-time event data across NBA, MLB, and soccer.

### Steps

1. **Create an account** at [platform.shipp.ai](https://platform.shipp.ai)
2. **Sign in** and navigate to **Settings > API Keys**
3. **Generate a new API key** — copy it immediately (it won't be shown again)
4. **Set the environment variable**:

```bash
# Add to your shell profile (~/.zshrc, ~/.bashrc, etc.)
export SHIPP_API_KEY="shipp_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

5. **Verify** by running:

```bash
curl -s -H "Authorization: Bearer $SHIPP_API_KEY" \
  "https://api.shipp.ai/api/v1/connections" | python3 -m json.tool
```

You should see a JSON response (even if the connections list is empty).

### API Key Format

Shipp API keys typically start with `shipp_live_` or `shipp_test_`. Use the
`live` key for production sports data.

### Rate Limits

Your rate limit depends on your Shipp.ai plan:

| Plan       | Requests/min | Connections | Notes                    |
|------------|-------------|-------------|--------------------------|
| Free       | 30          | 3           | Great for trying it out  |
| Starter    | 120         | 10          | Suitable for one sport   |
| Pro        | 600         | 50          | All three sports         |
| Enterprise | Custom      | Unlimited   | Contact sales            |

## Optional: Football-Data.org API Key

Enables soccer enrichment data including standings, fixtures, and team
details from football-data.org. Without this key, soccer panels on the
dashboard will be limited to Shipp.ai live data only.

### Steps

1. **Register** at [football-data.org/client/register](https://www.football-data.org/client/register)
2. **Confirm your email** — the API key is sent to your inbox
3. **Set the environment variable**:

```bash
export FOOTBALL_DATA_API_KEY="your-football-data-api-key"
```

### Free Tier Limits

- 10 requests per minute
- Access to major competitions: Premier League, La Liga, Bundesliga,
  Serie A, Ligue 1, Champions League
- No player-level stats (team and competition data only)

## No Key Required

The following external sources do not require API keys:

- **balldontlie API** — NBA player stats and season averages
  - Base URL: `https://api.balldontlie.io/v1`
  - Rate limit: ~30 requests/minute
  - Data: Player search, season averages, career stats

- **MLB Stats API** — MLB rosters, player stats, schedules
  - Base URL: `https://statsapi.mlb.com/api/v1`
  - Rate limit: No strict limit (be courteous, ~1 req/sec)
  - Data: Rosters, player stats, team info, game scores

## Python Dependencies

Install the required packages:

```bash
pip install requests rich
```

All other dependencies are from the Python standard library (`os`, `time`,
`logging`, `datetime`, `json`, `typing`).

## Environment Variable Summary

| Variable                | Required | Source             | Purpose                          |
|-------------------------|----------|--------------------|----------------------------------|
| `SHIPP_API_KEY`         | Yes      | platform.shipp.ai  | Live scores, schedule, events    |
| `FOOTBALL_DATA_API_KEY` | No       | football-data.org   | Soccer standings, fixtures       |

## Verifying Your Setup

Run the built-in smoke test:

```bash
cd skills/community/game-day-dashboard
python3 scripts/dashboard.py --once
```

This will attempt to:
1. Fetch live NBA scores (requires `SHIPP_API_KEY`)
2. Fetch NBA player stats via balldontlie (no key needed)
3. Fetch MLB schedule and scores (requires `SHIPP_API_KEY`)
4. Fetch soccer fixtures and standings (requires `FOOTBALL_DATA_API_KEY`)

Each panel will show either data or an error message indicating which
key is missing or which service is unavailable.

## Troubleshooting

### "SHIPP_API_KEY environment variable is not set"

Your shell session doesn't have the key. Make sure you either:
- Added `export SHIPP_API_KEY=...` to your shell profile and restarted the terminal
- Or ran the export command in the current session

### "Shipp API 401: Unauthorized"

The key is set but invalid. Double-check:
- No extra spaces or newline characters in the key
- The key is from the correct environment (live vs test)
- The key hasn't been revoked

### "Shipp API 402: Payment Required"

Your plan's quota has been exceeded. Check your usage at
[platform.shipp.ai/usage](https://platform.shipp.ai) or upgrade your plan.

### "Shipp API 429: Too Many Requests"

You've hit the rate limit. The dashboard automatically retries with backoff,
but if it persists, reduce polling frequency or upgrade your plan.

### Football-data.org returns empty results

Ensure `FOOTBALL_DATA_API_KEY` is set and valid. The free tier only covers
major European competitions — smaller leagues require a paid plan.

### balldontlie or MLB Stats API returning errors

These free APIs occasionally experience downtime. The dashboard will display
a "data unavailable" indicator for affected panels and retry automatically.

## Documentation Links

- **Shipp.ai Docs**: [docs.shipp.ai](https://docs.shipp.ai)
- **Shipp.ai API Reference**: [docs.shipp.ai/api](https://docs.shipp.ai/api)
- **balldontlie Docs**: [balldontlie.io](https://www.balldontlie.io)
- **MLB Stats API**: Community docs at [github.com/toddrob99/MLB-StatsAPI](https://github.com/toddrob99/MLB-StatsAPI)
- **Football-Data.org Docs**: [football-data.org/documentation](https://www.football-data.org/documentation/quickstart)
