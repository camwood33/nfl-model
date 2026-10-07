# Backtest Rules v1

**Frozen before any model result was seen.**
**Date: 2026-10-06**

---

## Scope

- Model predicts home and away scores for the full game and the first half,
  and turns them into strike probabilities using the model's own historical
  error spread. One shared model for all six markets.
- Unverified: that first-half scores can be derived from nflverse
  play-by-play (column names not checked).

## Decision cutoff (one rule for every game)

- Cutoff = 8pm Eastern, two calendar days before the game date. Thursday
  games use Wednesday 8pm Eastern. Eastern time everywhere.
- A game counts as finished 4 hours after kickoff.
- The cutoff is provisional until the injury timing check is done: for each
  game type, the share of 2009 to 2024 injury rows with a game status stamped
  before this cutoff. Any change from that check is recorded in this file as
  an amendment, made before any model outcome is looked at.
- Version 1 covers the game types that pass that check. Others are excluded
  and listed.

## Features (all computed using only games finished before the cutoff)

- Offensive and defensive efficiency: EPA/play (pass and rush separately) and
  success rate, opponent-adjusted, garbage time removed, recent games
  weighted more (decay rate is a swappable parameter).
- Pace: plays per game. Model form tests multiplicative (plays times points
  per play) against additive.
- Home field, plus a neutral-site flag.
- Rest days and a separate bye flag. Division game. Short week and primetime
  flags. Time-zone shift (needs a team time-zone table we build).
- Roof: dome, outdoors, retractable as its own category. The game-day open or
  closed value is never used.
- QB term: a QB rating from EPA/play, shrunk toward the league average for
  low-sample QBs. Starter status comes from the report as of the cutoff.
  - Out: swap in a league-average backup rating, estimated from past games
    where the starter sat.
  - Doubtful or Questionable: blend by P(plays | status), calibrated on
    training seasons using snap counts.
- Key starters out: a starter-value-out feature, player weights from
  pre-cutoff snap share. Kept only if validation improves. Also a flag in the
  betting filter.
- Regularization on all inputs.
- Excluded: weather in v1, yards/play, third-down %, red zone TD %, rolling
  point differential, raw turnover margin, head-to-head, head coach.
- nflverse's weather, starting QBs and lines are hindsight values and are
  never model inputs. Lines are used only as a benchmark.

## Tests, in order

1. **Leakage test:** rebuild a game's features after deleting every game not
   finished by its cutoff. Output must be identical. Nothing proceeds until
   it passes.
2. **Walk-forward validation:** for each season 2018 to 2024, train on the
   previous 3, 5 or 8 seasons and predict that season. Lookback length and
   additive vs multiplicative form are chosen by smallest prediction error,
   not profit. Near-ties go to the simpler or middle option. No Kalshi data
   and no 2025 data here.
3. **Information test:** regress actual margin and total on nflverse's
   closing line plus the model's prediction, over 2018 to 2024. A model
   coefficient indistinguishable from zero means no information beyond the
   market.
4. **Ceiling tests:** rerun with hindsight weather and with actual starting
   QBs. Labeled ceilings, never reported as performance.
5. **Baseline:** treat nflverse's close as fair value and trade Kalshi's
   price at the cutoff against it. Labeled a ceiling, since the close is not
   known at the cutoff.
6. **One-shot holdout:** the 2025 season against Kalshi candle prices at the
   cutoff. First check bid-ask width and volume on 2025 markets, before
   looking at any model output. Report ROI, CLV and calibration once.
7. **Forward test:** 2026 games after the freeze, paper picks logged before
   kickoff and graded as games finish.

## Kill rule

- If test 3 shows no added information, stop building features and pivot to
  the Kalshi-versus-close approach.

## Discipline

- Any change after seeing validation results counts as a new version, and
  the holdout runs once.
- First-half markets are judged on score accuracy against simple baselines
  plus forward data, since nflverse has no first-half lines.
- Ignore any ROI claim from fewer than a few hundred flagged bets.

## Open questions (unverified)

Listed in the original rules:

- Injury and play-by-play column names.
- Snap count coverage.
- The official Friday injury report deadline.
- 2025 market liquidity.
- Whether historical weather forecast archives exist.
- Thursday injury timing.
- Where historical preseason win totals and as-of-cutoff QB priors come from.

Ambiguities found while writing this file. None of these is decided here:

- **Game type:** not defined (for example Thursday, Sunday, Monday,
  Saturday, international, holiday, playoff).
- **Passing the injury timing check:** no threshold share is given.
- **Thursday cutoff vs "one rule for every game":** the Thursday rule is a
  separate case. Not stated: whether it also covers Thanksgiving, the
  season-opening Thursday, or other non-Sunday games such as Friday,
  Saturday and international games.
- **Near-ties (test 2):** no tolerance is given. Also not stated: which rule
  wins when "simpler" and "middle" point to different options. Additive vs
  multiplicative has no middle option, and for lookback length "simpler"
  isn't defined.
- **Prediction error metric (test 2):** the metric is not named, and neither
  is how full-game and first-half errors, or home and away errors, are
  combined.
- **"Kept only if validation improves" (key starters out):** the metric and
  the margin of improvement are not given.
- **"Indistinguishable from zero" (test 3):** no significance level or test
  is given. Also not stated: whether margin and total are judged separately
  and how a split result works under the kill rule.
- **Error spread for strike probabilities:** the distribution form is not
  given, nor whether it is estimated per market or shared.
- **2025 holdout training window:** which seasons train the model that
  predicts 2025, and whether the lookback chosen in test 2 is reused.
- **Kalshi price at the cutoff (tests 5 and 6):** which price (bid, ask,
  mid, last trade or candle close), and how to handle no candle at the
  cutoff.
- **Test 5 season range:** which seasons of Kalshi data the baseline uses.
- **Bid-ask and volume check (test 6):** no thresholds are given, and
  neither is what happens if 2025 liquidity is too thin.
- **Ceiling test seasons (test 4):** which seasons and which metric.
- **Early-season features:** how features are built when few or no
  current-season games have finished before the cutoff.
- **Primetime and short week:** not defined.
- **Garbage time and opponent adjustment:** neither method is defined.
- **QB shrinkage and "low-sample":** the sample threshold and how strongly
  ratings are shrunk are not given.
- **"Starter" (key starters out):** not defined.
- **"Few hundred" flagged bets:** no exact minimum.
- **"The freeze" (test 7):** whether this is the date of this file or a later
  model freeze.
- **Simple baselines for first-half markets:** not specified.
- **Regularization:** the type and how its strength is chosen are not
  specified.

---

## Amendment 1 (2026-10-06, before any check or model result)

- Every remaining item under "Ambiguities found while writing this file" will
  be settled by a dated amendment committed before the first run of the step
  that depends on it, and always before that step's results are seen. Nothing
  is settled after a result.
- Game types for the injury timing check: group each regular season game by
  the weekday of its Eastern game date (Thursday, Friday, Saturday, Sunday,
  Monday), plus a separate group for neutral-site games (nflverse location =
  Neutral, regular season only). The Thursday exception (Wednesday cutoff)
  applies to every Thursday game, including Thanksgiving and season openers.
  Playoffs are excluded from this check.
- A group with fewer than 100 games in 2009 to 2024 is not tested and is
  excluded from version 1.
- A group passes if, for 2009 to 2024, both (a) at least 90% of all injury
  rows with a game status (Out, Doubtful or Questionable) and (b) at least
  90% of the QB rows with a game status were stamped at or before the cutoff.
  Use the nflverse injury column that holds the game designation and say
  which one it is.
- A tested group that fails is tried once more at 8pm Eastern the day before
  its game date, under the same pass rule. If it fails again, it is excluded
  from version 1 and listed.
- Time zone of date_modified: determine it from the data (for example where
  the Friday stamps cluster by hour) and write the evidence in the file. If
  it can't be determined, report the check as inconclusive instead of
  assuming a time zone.

---

## Amendment 2 (2026-10-06): injury timing check results

Data: nflverse injuries 2009 to 2024 (`injuries_YYYY.parquet`), regular
season rows only (`game_type == REG`), and nflverse schedules
(`games.parquet`) for game dates, weekday and `location`.

### Designation column

The game designation is `report_status`. Values in 2009 to 2024 regular and
postseason rows: Questionable 22,333, Probable 17,400, Out 14,725, Doubtful
3,260, Note 6, blank 26,960. Only Out, Doubtful and Questionable count as a
game status under Amendment 1. Probable and Note rows are not counted.

### Time zone of `date_modified`: inconclusive

`date_modified` is stored with a UTC label. The data shows two eras:

- **2021 to 2024: UTC, determined.** Friday stamps on status rows cluster at
  17 to 21h UTC, with a median of about 19.3 to 19.6h UTC while daylight time
  is in effect and about 19.8 to 20.5h UTC after it ends. A shift of about
  +1 hour at the end of US daylight time is what a true UTC clock shows when
  the reports are posted on Eastern local time. That puts the median at
  about 3:15 to 3:30pm Eastern.
- **2010 to 2020: not determined.** Friday stamps cluster at 10 to 13h
  (median about 11.6 to 12.4h). The cluster does not move when US daylight
  time ends (for example 2013: 11.85h with daylight time, 11.62h without).
  So these stamps are local clock time in a daylight-saving zone, labeled as
  UTC. They are not true UTC. The data does not show which zone: Eastern,
  Central, Mountain and Pacific would all produce this pattern.
- **Both eras:** West Coast and Mountain teams' Friday stamps sit about 1 to
  1.25 hours later than East Coast teams' (2010 to 2020 medians: east 11.5h,
  west/mountain 12.8h; 2021 to 2024: east 19.4h, west/mountain 20.6h).
  So the stamps are real post times, not one batch scrape time.
- **2009:** 2,278 of 2,288 status rows have no `date_modified`. The other 10
  share a single stamp, 2010-01-01 09:23:14.

The 2010 to 2020 time zone can't be determined, so per Amendment 1 the check
is **inconclusive** for every tested group. No stamped-by-cutoff shares were
computed, under any assumed time zone. No share has been seen.

### Per-group results

Groups use the weekday of the schedule `gameday` (Eastern game date),
regular season 2009 to 2024. Rows are injury rows with status Out, Doubtful
or Questionable, joined to games on season, week and team.

| Group | Games | Status rows | QB status rows | Rows with no stamp (QB) | Share by cutoff, all / QB | Result |
|---|---|---|---|---|---|---|
| Thursday | 256 | 2,550 | 74 | 77 (1) | not computed | Inconclusive |
| Friday | 5 | 47 | 0 | 6 (0) | not tested | Excluded: under 100 games |
| Saturday | 86 | 837 | 31 | 13 (0) | not tested | Excluded: under 100 games |
| Sunday | 3,517 | 33,285 | 930 | 2,033 (67) | not computed | Inconclusive |
| Monday | 286 | 2,511 | 58 | 149 (0) | not computed | Inconclusive |
| Neutral site | 54 | 555 | 14 | 9 (0) | not tested | Excluded: under 100 games |

The fallback cutoff (8pm Eastern the day before) was not tried, because no
tested group reached a pass or fail result.

Other facts from the run:

- 2 status rows (BUF and CIN, 2022 week 17) have no schedule row. That is
  the BUF at CIN game, which has no row in nflverse schedules. They are not
  in any group.
- 9 regular season games fall on a Tuesday (5) or Wednesday (4). Amendment 1
  puts them in no group.
- The 54 neutral-site games are also counted in their weekday groups
  (Sunday 47, Monday 6, Friday 1).

### Version 1 membership, by the rules above

- **Excluded from version 1:** Friday, Saturday and neutral-site games
  (each under 100 games in 2009 to 2024).
- **Not decided:** Thursday, Sunday and Monday. The check is inconclusive, and
  the rules say nothing about what follows an inconclusive check. No group is
  in version 1 yet.

### Open questions raised by this check (not decided here)

- What follows an inconclusive check. For example: fix the 2010 to 2020
  time zone from an outside source, run the check on 2021 to 2024 only, or
  test each era separately. Any choice must be committed as an amendment
  before any share is computed.
- Rows with no `date_modified` (almost all of 2009): count them as not
  stamped by the cutoff, or leave them out of the denominator.
- Neutral-site games also sit in a weekday group. Does excluding the neutral
  group remove them from version 1 even when their weekday group passes?
- Tuesday and Wednesday games are in no group.
- The Thursday fallback (8pm Eastern the day before) is the same as the
  Thursday primary cutoff (Wednesday 8pm), so the fallback cannot change a
  Thursday result.

---

## Amendment 3 (2026-10-06, before any share is computed)

- Data: 2010 to 2024 regular season rows. 2009 is excluded entirely because
  it has no timestamps (a data gap, not a timing result). Any other row with
  a game status but no stamp counts as not stamped in time, and the count is
  reported.
- Groups are disjoint: Thursday, Sunday and Monday games exclude neutral-site
  games. Neutral-site games are left out of version 1. The 9 Tuesday and
  Wednesday games and the cancelled 2022 Week 17 BUF@CIN rows are left out
  and listed.
- Time zone: 2021 to 2024 stamps are true UTC. 2010 to 2020 stamps are local
  clock time in an unknown US zone, so no zone is assumed. Compute every
  share twice for 2010 to 2020: once treating the stamps as Eastern (best
  case) and once as Pacific, which is 3 hours later in Eastern (worst case).
  2021 to 2024 use UTC converted to Eastern. Pool 2010 to 2024 under each
  assumption.
- A group passes if both criteria (all Out, Doubtful and Questionable rows,
  and QB rows alone) are at least 90% under the worst case. It fails if
  either criterion is under 90% even under the best case. A group in between
  is left out of version 1 and listed. No threshold changes after results. A
  later amendment may re-include a group only with new evidence about the
  zone and the same thresholds.
- Thursday has no day-before fallback, since it would equal the main cutoff.
  Other groups that fail use the one-time day-before fallback from
  Amendment 1, under the same rule.
- Also report 2021 to 2024 alone (exact UTC) for information. It is not used
  for pass or fail.
- Note: a row stamped after the cutoff counts as not available. This
  understates availability, since a later edit may have kept an earlier
  designation.

---

## Amendment 4 (2026-10-06): injury timing check results under Amendment 3

Run exactly as Amendment 3 defines it: nflverse injuries and schedules,
2010 to 2024 regular season. Rows have `report_status` Out, Doubtful or
Questionable and are joined to games on season, week and team. Cutoff is 8pm
Eastern two calendar days before the Eastern game date, or Wednesday 8pm for
Thursday games. A row counts if stamped at or before the cutoff. No model was
run and no game result was used.

Checks before computing:
- No status row in 2010 to 2024 lacks a stamp (count: 0 in every group).
- No 2010 to 2020 stamp falls in a daylight-saving gap or overlap hour in
  either Eastern or Pacific, so every stamp converts to exactly one time.

### Results

Best case: 2010 to 2020 stamps read as Eastern clock time. Worst case: read
as Pacific clock time (3 hours later in Eastern). 2021 to 2024 is true UTC
converted to Eastern in both. The 2021 to 2024 exact column is for
information only.

| Group (non-neutral) | Games | Criterion | Rows | No stamp | Best case | Worst case | 2021-24 rows | 2021-24 exact |
|---|---|---|---|---|---|---|---|---|
| Thursday | 247 | All status rows | 2,473 | 0 | 99.64% | 99.64% | 720 | 99.44% |
| Thursday | 247 | QB rows | 73 | 0 | 100.00% | 100.00% | 24 | 100.00% |
| Sunday | 3,243 | All status rows | 30,750 | 0 | 99.09% | 99.09% | 8,613 | 97.94% |
| Sunday | 3,243 | QB rows | 852 | 0 | 99.53% | 99.53% | 259 | 99.61% |
| Monday | 263 | All status rows | 2,314 | 0 | 99.09% | 98.88% | 674 | 98.52% |
| Monday | 263 | QB rows | 55 | 0 | 98.18% | 98.18% | 12 | 91.67% |

All three groups clear 90% on both criteria under the worst case, so all
three **pass**. No group failed, so the day-before fallback was not used.

### Version 1 membership

- **In version 1:** regular season Thursday, Sunday and Monday games that are
  not neutral-site, at the cutoff in the main rules (8pm Eastern two days
  before; Thursday games Wednesday 8pm Eastern). The cutoff is no longer
  provisional for these groups.
- **Excluded and listed:**
  - Neutral-site games: 53 in 2010 to 2024 (Amendment 3).
  - Friday and Saturday games: under 100 games (Amendment 2). Non-neutral
    counts in 2010 to 2024 are Friday 3 and Saturday 85.
  - The 9 Tuesday and Wednesday games (Amendment 3): 2010_16_MIN_PHI,
    2012_01_DAL_NYG, 2020_05_BUF_TEN, 2020_12_BAL_PIT, 2020_13_DAL_BAL,
    2021_15_SEA_LA, 2021_15_WAS_PHI, 2024_17_KC_PIT, 2024_17_BAL_HOU.
  - The cancelled 2022 Week 17 BUF@CIN game: 2 status rows (BUF, CIN), no
    schedule row.
  - Playoff games (excluded from the check by Amendment 1).
  - 2009 rows (Amendment 3, no timestamps).

---

## Amendment 5 (2026-10-06, before any feature or result)

- Plays used for efficiency: pass and rush plays only, excluding kneels,
  spikes and plays with null epa. Garbage time: any play with wp below 0.05
  or above 0.95 is removed.
- Opponent adjustment: ridge regression of play-level EPA (pass and rush
  separately) and of success on offense-team and defense-team indicators plus
  a home-field term, fit only on games finished before the cutoff, with
  recency weights. Ridge strength is chosen in walk-forward validation from a
  predefined grid.
- Recency: exponential weights by games ago, half-life grid of 4, 8 and 16
  games, chosen in validation.
- Early season: current-season ratings are blended with prior-season-end
  ratings shrunk toward the league average, fading with games played. The
  fade length is a validation parameter, with a grid of fully faded by game
  4, 8 or 12. The preseason win total prior is not part of version 1, since
  no historical source exists. 2010 is never predicted.
- Pace: a team's plays per game (the plays above), recency weighted, not
  opponent adjusted in version 1.
- Short week: rest days of 5 or fewer for that team. Primetime: scheduled
  kickoff at or after 8:00pm Eastern.
- Time-zone shift: hours between the team's home time zone and the game
  site's time zone, using a team-to-zone table by season (franchise moves
  such as the Rams in 2016 handled by season). Home team shift is 0.
  Version 1 has no neutral-site games.
- QB rating: EPA per dropback (pass attempts plus sacks), shrunk toward the
  league-average QB with prior strength k dropbacks, rating = (n times QB
  EPA per dropback plus k times league average) divided by (n plus k), where
  k comes from a validation grid of 100, 200 and 400. A QB with fewer than
  200 dropbacks before the cutoff is low-sample. Who starts is settled later,
  with the injury and snap data. Not settled here: starter status, the "key
  starters out" definition, and every other open ambiguity. Each is settled
  by its own amendment before the step that needs it.
- First-half scores come from play-by-play (game_half = Half1) and must
  reconcile to final scores for every game.
- Data cleaning: before any feature is built, drop exact duplicate plays as
  defined in Step 1a. Any game whose scores still don't match the schedule's
  final score is excluded from features and training and is listed (the 2011
  DET at NO game is the only one known). No play-level repair is done.
- Franchise IDs: use today's codes everywhere (LA, LAC, LV). Schedule and
  injury codes STL, SD and OAK map to LA, LAC and LV, and this applies to all
  joins and features.
- Snap counts start in 2013 (2010 and 2011 have none, 2012 is empty). The
  games used to train the model come from 2013 onward only. Team ratings may
  use play-by-play from 2010 as history. Lookback options are cut off at
  2013, which shortens them for the 2018 to 2020 test seasons.

### Data cleaning results

"Step 1a" above means: drop play-by-play rows that repeat on `game_id`,
`qtr`, game clock (`time`) and the full play description (`desc`), keeping
the first. Run on nflverse play-by-play 2010 to 2024 (all rows, regular and
postseason).

- Duplicate rows dropped: 6 in total, all in 2011 (0.013% of 47,448 plays),
  all from 2011_14_OAK_GB (4 run, 1 pass, 1 no_play). 0 in every other
  season. No season exceeds 0.5%.
- Score reconciliation after dropping (maximum running `total_home_score`
  and `total_away_score` vs schedule final score): 4,077 of 4,078 games
  match. Still failing: **2011_13_DET_NO**, play-by-play 37-23 vs schedule
  31-17 (home-away). Two touchdowns appear twice with slightly different
  descriptions, so the exact-duplicate rule does not remove them. This game
  is excluded under the data cleaning rule.
- Pass and rush plays (`pass == 1` or `rush == 1`, after dropping duplicates,
  before removing kneels and spikes) missing a value:

  | Season | Pass/rush plays | No epa | No success | No wp |
  |---|---|---|---|---|
  | 2010 | 34,579 | 1 | 1 | 0 |
  | 2011 | 34,945 | 0 | 0 | 0 |
  | 2012 | 35,389 | 0 | 0 | 0 |
  | 2013 | 35,635 | 1 | 1 | 1 |
  | 2014 | 35,339 | 0 | 0 | 0 |
  | 2015 | 35,675 | 0 | 0 | 0 |
  | 2016 | 35,394 | 0 | 0 | 0 |
  | 2017 | 35,058 | 0 | 0 | 0 |
  | 2018 | 34,883 | 0 | 0 | 0 |
  | 2019 | 35,204 | 2 | 2 | 0 |
  | 2020 | 35,605 | 0 | 0 | 0 |
  | 2021 | 37,310 | 0 | 0 | 0 |
  | 2022 | 36,870 | 0 | 0 | 0 |
  | 2023 | 37,053 | 0 | 0 | 0 |
  | 2024 | 36,724 | 0 | 0 | 0 |
