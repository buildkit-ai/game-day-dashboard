# GUI Specification: game-day-dashboard

## Design Direction
- **Style:** Dark sports bar theme with a data-dense, multi-panel scoreboard layout. High contrast typography against deep backgrounds. Information architecture inspired by broadcast control rooms and financial terminals applied to live sports.
- **Inspiration:** ESPN GameCast live scoring interface, Bloomberg Terminal multi-panel density, The Athletic dark-mode game pages on Dribbble/Behance
- **Mood:** Intense, immersive, real-time, electric

## Layout
- **Primary view:** Three-column layout. Left sidebar (20%) for league/game selector and standings snapshot. Center panel (55%) for dominant live scoreboard with quarter/period breakdowns and key stats. Right panel (25%) for chronological play-by-play feed with auto-scroll.
- **Mobile:** Collapses to single-column stacked view. Scoreboard becomes sticky top card, play-by-play scrolls below. Sidebar becomes a bottom sheet drawer accessible via hamburger icon.
- **Header:** Full-width dark bar containing: Shipp logo (left), sport/league selector tabs (center), live clock + connection status indicator (right). Height: 56px.

## Color Palette
- Background: #0D1117 (Midnight Void)
- Surface: #161B22 (Carbon Panel)
- Primary accent: #22D3EE (Electric Cyan) — live scores, active game highlights, pulsing indicators
- Success: #34D399 (Emerald Glow) — scoring plays, positive stat changes
- Warning: #EF4444 (Alert Red) — turnovers, fouls, injury flags, breaking alerts
- Text primary: #F0F6FC (Ice White)
- Text secondary: #8B949E (Slate Grey)

## Component Structure
- **ScoreboardCard** — Central score display with team logos, current score, period/quarter indicator, game clock, and live pulsing dot. Supports pre-game, live, and final states.
- **PlayByPlayFeed** — Vertically scrolling timeline of game events with timestamp, event icon, and description. Auto-scrolls to latest; user scroll pauses auto-scroll.
- **GameSelector** — Left sidebar list of today's games grouped by league, each showing mini score and status badge (LIVE/FINAL/UPCOMING).
- **StatsBar** — Horizontal comparison bars (e.g., rebounds, assists) rendered between two team columns within the scoreboard.
- **LiveIndicator** — Pulsing cyan dot with "LIVE" label and "Updated Xs ago" subtext. Transitions to grey "FINAL" when game ends.
- **QuarterBreakdown** — Tabular row showing score per period/quarter with totals, styled as a compact data strip beneath the main score.
- **AlertBanner** — Full-width dismissible banner for breaking events (e.g., ejection, injury timeout). Red background with slide-down animation.

## Typography
- Headings: Inter Bold, 20-28px, letter-spacing -0.02em, #F0F6FC
- Body: Inter Regular, 14-16px, line-height 1.5, #8B949E for secondary, #F0F6FC for primary
- Stats/numbers: JetBrains Mono Medium, 32-48px for scores, 14-18px for stat values, tabular-nums enabled

## Key Interactions
- **Game selection:** Clicking a game in the left sidebar transitions the center scoreboard and right play-by-play to the selected game with a 200ms cross-fade.
- **Play-by-play auto-scroll:** Feed auto-scrolls to newest events. Scrolling up pauses auto-scroll and shows a "Jump to latest" floating button at the bottom.
- **Score flash:** When a score changes, the score digits animate with a brief scale-up (1.15x) and cyan glow pulse lasting 600ms.
- **Live/Final toggle:** Game status transitions from pulsing cyan LIVE indicator to static grey FINAL badge with a fade animation.
- **Stat bar hover:** Hovering over a stats comparison bar reveals exact values in a tooltip and highlights the leading team's bar segment.
- **Mobile swipe:** On mobile, horizontal swipe on the sticky scoreboard card navigates between games.

## Reference Screenshots
- [ESPN GameCast Dark Mode](https://dribbble.com/search/espn-gamecast-dark) — Multi-panel live scoring layout with play-by-play sidebar and dark theme
- [Sports Dashboard UI Kit on Behance](https://www.behance.net/search/projects?search=sports+dashboard+dark) — Dark scoreboard cards with real-time data density and stat visualizations
- [Bloomberg Terminal Sports Concept on Mobbin](https://mobbin.com/search/sports-dashboard) — Data-dense multi-panel layout inspiration for information hierarchy
