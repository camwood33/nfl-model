# Data sources: nflverse and Kalshi history

Everything here was checked on 2026-10-04 unless it is marked **unverified**.
nflverse files live under `data/historical/` (git-ignored) and were read with a
separate virtualenv at `.venv/` (also git-ignored), so `/usr/bin/python3` (used by
the launchd jobs) has no new packages.

## 1. nflverse conventions (schedules, `games.parquet`)

Source: GitHub release assets at `nflverse/nflverse-data` (tags `schedules`,
`pbp`, `injuries`).

| Dataset | Seasons | Size |
|---|---|---|
| schedules (`games.parquet`) | 1999–2026, current through 2026 week 4 | 0.5 MB |
| play-by-play (one file per season) | 1999–2026, current through 2026 week 4 | 493 MB total |
| injuries (one file per season) | 2009–2026, current through 2026 week 4 | 2.0 MB total |

```
result      = home_score - away_score         (7338/7338 completed games)
total       = home_score + away_score         (7338/7338)
spread_line = expected HOME margin: positive = home team favored.
              It is NOT the home team's betting line (that is -spread_line).
total_line  = game total points line (over/under).

Covering:
  home covers   if result >  spread_line
  away covers   if result <  spread_line
  push          if result == spread_line   (possible only on whole-number lines)
  over          if total  >  total_line;  push if equal

Mapping to Kalshi (KXNFLSPREAD "TEAM wins by over X", X = floor_strike):
  home-team strike settles YES  iff  result  > X
  away-team strike settles YES  iff  -result > X
  KXNFLTOTAL strike settles YES iff  total   > X
```

How it was verified:
- **Sign of `spread_line`:** compared with Kalshi's main line in the T-3 snapshot
  for all 14 games of 2026 week 4. The main line is the favored team's spread
  strike whose before-fee midpoint is closest to 0.5. The sign agreed on 14/14.
  The 7 not-yet-played games compared on older snapshots also agreed (7/7).
- **Size:** no game was more than 1.0 point apart, on either spread or total.
  Exactly 1.0 apart were the KC@LV spread (Kalshi −5.5 vs nflverse −4.5) and the
  totals for JAC@CIN (52.5 vs 51.5), GB@TB (37.5 vs 38.5) and DAL@HOU (49.5 vs 48.5).
- **Why 0.5 gaps are expected:** Kalshi strikes are all X.5, so they never push.
  nflverse lines can be whole numbers (7.0, 3.0).
- **Settlement:** all 604 settled spread and total strikes from the 13 finished
  2026-10-04 games settled as nflverse `result`/`total` predicts.

Coverage of candidate fields (completed games):
- **No missing values in any season:** `away_rest`/`home_rest`, `roof`,
  `div_game`, `away_qb_id`/`home_qb_id`, `spread_line`, `total_line`.
- **Moneylines and odds** (`*_moneyline`, `*_spread_odds`, `over_odds`/`under_odds`):
  - missing for all of 1999–2005;
  - partly missing in 2006 (47 games), 2008 (73) and 2009 (14);
  - complete from 2010, except one game in 2017.
- **`temp`/`wind`:** blank by design for dome and closed-roof games. For outdoor
  or open-roof games, 0–14 are missing per season, except **2022 (91)** and
  **2023 (41)**.

## 2. ID mapping

- **nflverse to ESPN:** the schedules `espn` column is the ESPN event id, the
  same id our bets table stores as `game_id`. It is filled for every game from
  1999 to 2026. All 64 games of 2026 weeks 1–4 matched the ESPN scoreboard on
  id and teams.
- **Team codes:**

  | Team | nflverse | ESPN | Kalshi |
  |---|---|---|---|
  | Rams | `LA` | `LAR` | `LA` in 2025, `LAR` in 2026 |
  | Washington | `WAS` | `WSH` | `WAS` |
  | Jacksonville | `JAX` | `JAX` | `JAC` |

  All other teams use the same code in all three. ESPN to Kalshi is already
  handled by `_ESPN_TO_KALSHI_TEAM` in `data/collect/kalshi_lines.py`.
- **Kalshi event tickers** look like `{series}-{YYMONDD}{AWAY}{HOME}`. The date
  is the US Eastern game date.
- **Match on season, week and teams, not the ticker date.** Kalshi keeps a
  ticker's original date when a game is moved: two 2025 week 18 games played on
  Jan 3 kept tickers dated Jan 4 (`26JAN04CARTB`, `26JAN04SEASF`).
- **2025 match rate:** 281 of 285 nflverse games matched a historical KXNFLGAME
  event once the Rams were coded `LA`. The four misses:
  - the two rescheduled week 18 games above;
  - NE@DEN on 2026-01-25 (conference game), which has no historical KXNFLGAME
    event;
  - the Super Bowl (SEA@NE, 2026-02-08), which is not in KXNFLGAME.
- **Super Bowl series:** KXSB exists and holds Super Bowl markets, but it was not
  checked whether KXSB has a per-game market like KXNFLGAME (**unverified**). The
  first-half series (KXNFL1HSPREAD, KXNFL1HTOTAL, KXNFL1HWINNER) do include the
  Super Bowl game.
- **Preseason:** Kalshi lists preseason games (2025 had them from Aug 7), but
  nflverse schedules have no preseason games, so those never match.
- **SF@SEA divisional game:** it has two Kalshi events, `26JAN17SFSEA`
  (zero volume, matches nflverse's date) and `26JAN18SFSEA`. Which one carried
  the trading is **unverified**.

## 3. Point-in-time limits (backtest rules)

- **Weather (`temp`, `wind`) is a hindsight value.** It is blank before kickoff
  and filled in after the game; no future game has a value. Today's games were
  still blank in schedules hours after kickoff. Play-by-play already had a text
  `weather` field for them, and where schedules had a value it matched
  play-by-play 34/34. Whether that is observed or forecast weather is
  **unverified**. Two dome games carried outdoor weather, so it looks like city
  weather. Pre-game forecasts must come from a separate source.
- **Starting QBs (`*_qb_id`, `*_qb_name`) are overwritten.** Future games already
  carry a projected QB (17 games). For past games the value is the QB who
  actually started, with no record of what was expected beforehand.
- **Lines (`spread_line`, `total_line`, moneylines) are overwritten as they
  move.** 16 future games already had a `spread_line`. For past games the value
  is the last one nflverse captured. When that capture happened, and whether it
  is the true close, is **unknown**.
- **Injuries are one row per player per week.** Each row has that week's final
  game status and a single practice status; earlier days of the week are not
  kept.
  - **2009–2024** rows have `date_modified`. It falls in game week, mostly on
    Friday. 26 of 84,667 rows are stamped after that team's kickoff, with
    kickoff taken from nflverse `gameday` + `gametime` read as US Eastern.
  - **2025 and 2026** have no timestamp column, so the report day can only be
    inferred from the week number.

## 4. Kalshi history

- **Access:** public, no credentials. Base URL
  `https://api.elections.kalshi.com/trade-api/v2`, the same one the collector
  uses.
- **Cutoff:** `GET /historical/cutoff` returned `market_settled_ts = 2026-08-05`.
  - Markets that settled before then are served by `/historical/markets` and
    `/historical/markets/{ticker}/candlesticks`.
  - Markets that settled after it, i.e. everything this season, are only on the
    live routes: `/markets`, `/series/{series}/markets/{ticker}/candlesticks`,
    and the batch `/markets/candlesticks?market_tickers=…`. The historical route
    returns 404 for them.
- **Candle intervals:** `period_interval` accepts only 1, 60 and 1440 minutes
  (5 returned a 400 error). At most 5,000 candles per request.
- **Candle fields:**
  - `end_period_ts`;
  - `yes_bid` and `yes_ask` (open/high/low/close);
  - trade `price` (open/high/low/close/mean/previous);
  - `volume` and `open_interest`.

  There is no "no" side; no ask = 1 − yes bid. The historical route uses plain
  names (`close`, `volume`). The live route uses suffixed names
  (`close_dollars`, `volume_fp`).
- **Other candle behavior:** daily candles end at 04:00 UTC. Quiet markets have
  gaps in the 1-minute series.

Series coverage (earliest to latest game date reached):

| Series | Our label | Coverage |
|---|---|---|
| KXNFLGAME | ML | 2025-07-31 → 2026-01-25 historical (333 events, includes preseason), then 2026 on the live route |
| KXNFLSPREAD | SPREAD | 2025-08-21 → 2026-02-08 historical (301 events), then 2026 live |
| KXNFLTOTAL | TOTAL | 2025-08-21 → 2026-02-08 historical (301 events), then 2026 live |
| KXNFL1H | 1H ML | none historical; live from the 2026-08-06 game (series opened 2026-08-05). In 2025 the first-half winner market was KXNFL1HWINNER, 21 markets, 2025 playoffs only |
| KXNFL1HSPREAD | 1H SPREAD | 2025 playoffs only (2026-01-17 → 2026-02-08, 7 events), then 2026 live |
| KXNFL1HTOTAL | 1H TOTAL | 2025 playoffs only (2026-01-17 → 2026-02-08, 7 events), then 2026 live |

Nothing from before the 2025 season was found under these series or the
alternative names tried (NFLGAME, NFL, KXNFLGAMES). 4 of the 666 historical
KXNFLGAME markets show zero volume.

**Our T-3 snapshots vs. Kalshi 1-minute candles (2026-10-04):**
- **Method:** our `yes_ask`/`no_ask` include the taker fee (0.07·p·(1−p)), so
  the fee was applied to the candle values before comparing.
- **Full-game moneyline:** 26/26 rows matched exactly on both sides, across all
  13 finished games.
- **All six markets (12 games, 945 rows):** 864 rows had candles on both sides
  of the snapshot. Of those, 846 yes asks (97.9%) and 844 no asks matched exactly.
- **No candle:** 81 rows fell in 1-minute gaps. The one checked had a flat price
  across the gap, equal to ours.
- **Mismatches:** 18 rows, all where the price moved inside the snapshot's
  minute. Our row matched the price from about one minute earlier. For example,
  `KXNFLSPREAD-26OCT04DENSF-SF7` at 20:22:04 UTC equals the 20:21 close.

## 5. Still unverified

- When nflverse captures `spread_line`/`total_line`/moneylines, and whether past
  values are true closing lines.
- Whether nflverse weather is observed at kickoff or a forecast.
- Which day of the week the single injury `practice_status` refers to.
- The cause of the ~1-minute lag between our snapshot timestamps and the
  candles: our timestamp set before the fetch, API caching, or candle boundaries.
- Accuracy of 2025 historical candles; we have no snapshots of our own to
  compare them against.
- Whether KXSB has a per-game Super Bowl market comparable to KXNFLGAME.
- Why 4 historical KXNFLGAME markets have zero volume, and which SF@SEA
  divisional event actually traded.
- The `spread_line` sign check covers one week (14 games, plus 7 future games on
  older snapshots). The `result`/`total` definitions are checked across all
  seasons.
