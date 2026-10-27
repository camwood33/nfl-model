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

---

## Amendment 6 (2026-10-07, before any model run)

- Rating layer: version 1 uses opponent-adjusted ratings, the ridge
  regression already set in the Features section and Amendment 5. A raw-input
  version can be built later as a separate version.
- QB inside the adjustment: the pass-play ridge regressions (EPA and success
  rate) also include a passer indicator for each QB on dropbacks. The team
  offense rating then means everything about the team except its QB, and each
  QB gets his own effect. Rush plays use team indicators only, with no QB
  term in version 1. Defense and home field terms stay as in Amendment 5.
- QB rating: the QB's effect from the pass-play EPA regression, shrunk by the
  ridge penalty. The success-rate regression's QB effects are not used as
  features. Their only role is to keep team success ratings free of the QB.
  This replaces the formula with k in Amendment 5, and the k grid (100, 200,
  400) is removed. The 200-dropback low-sample line stays as a label.
- Known limit: a QB who has only played for one team can't be cleanly
  separated from that team's other strengths. The split is identified from
  QBs who changed teams and from backups who played in place of a starter,
  and otherwise leans on the ridge penalty.
- Ablation: test 2 also runs once with the QB term removed (from both pass
  regressions and as a feature). Test 2's rule applies unchanged to this
  comparison: the run without the QB term is the simpler option, so it wins
  near-ties, and the QB term stays only if the run with it has a smaller
  prediction error by more than the near-tie tolerance. The tolerance is set
  by its own amendment before test 2 runs. This is one extra comparison, not
  a new grid.

### Open questions added by this amendment

Each is settled by its own amendment before the first model run.

- The ridge penalty grid for the QB indicator, separate from the team
  penalty.
- How a QB's effect carries across seasons.
- How scrambles are handled. First check how nflverse codes them (the
  `play_type`, `pass`, `rush`, `qb_dropback` and `qb_scramble` columns) and
  report what is found before proposing anything. Not decided here.
- The dropback definition used for the passer indicator.

---

## Amendment 7 (2026-10-07, before any model run)

- Dropback definition (settles the open question in Amendment 6, "the
  dropback definition used for the passer indicator"): a dropback is a play
  with qb_dropback = 1. This includes scrambles.
- Scrambles (settles the open question in Amendment 6, "how scrambles are
  handled"): scramble plays are dropbacks. They go in the pass-play
  regressions with a passer indicator, and nowhere else. nflverse codes them
  as play_type run with qb_scramble = 1 and qb_dropback = 1.
- Play set (changes Amendment 5, which it replaces for efficiency plays and
  for pace): efficiency plays are plays with play_type pass or run only, and
  they must also have pass = 1 or rush = 1 as in Amendment 5. Plays with
  play_type no_play (penalty-wiped), kneels, spikes and two-point attempts
  (the two_point_attempt column) are excluded, along with null epa and
  garbage time as in Amendment 5. The 77 plays with play_type pass or run but
  pass = 0 and rush = 0 are excluded and counted: 74 from 2010 and 2011 coded
  'play under review' (4 of them sacks), and 3 run plays (2011_02_STL_NYG,
  2012_10_OAK_BAL, 2016_05_NE_CLE). Count every exclusion by reason and
  season in the file.
- Pace follows this play set: a team's plays per game is counted over the
  efficiency plays defined here.
- Each play goes in exactly one regression: a play with qb_dropback = 1
  (scrambles included) goes in the pass-play regressions with a passer
  indicator. A play with rush = 1 and qb_dropback = 0 goes in the rush
  regressions. Any play that fits neither is excluded and counted.
- QB identity: passer_id is the QB ID for the passer indicator, including on
  scrambles, because passer_player_id and rusher_id are blank on scrambles
  (rusher_player_id holds the scrambler). Step 1 result: on 60 sampled
  scrambles (15 each from 2010, 2016, 2020, 2024), passer_id matched the
  scrambler 59 times, and the one miss was a blank. On all 12,549 scramble
  runs, passer_id equals rusher_player_id on every play where both are
  filled in. All ID columns use the GSIS format, 00- followed by 7 digits.
- Dropbacks with a blank passer_id (the 18 non-QB scrambles, and up to 0.29%
  of dropbacks in a season) are excluded and counted by season.
- Nothing else changes. The other open questions from Amendment 6 stay open,
  except the two settled above.

### Exclusion counts by reason and season

Data: nflverse play-by-play 2010 to 2024, regular season and postseason, after
the Amendment 5 cleaning (Step 1a duplicates dropped, 2011_13_DET_NO
excluded). Candidate plays are rows with pass = 1, rush = 1, or play_type
pass, run, qb_kneel or qb_spike. Reasons are applied in the column order
below, and each play is counted once, under the first reason it meets.
"Other play_type" is punt 17, blank 4 and extra_point 1. "Fits neither
regression" is 22 run plays with pass = 1, rush = 0 and qb_dropback = 0
(for example illegal forward passes and plays reversed on review).

| Season | Candidate plays | no_play | kneel | spike | other play_type | pass=0 and rush=0 | two-point attempt | null epa | garbage time | fits neither regression | dropback, blank passer_id | kept: pass regression | kept: rush regression |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2010 | 35,047 | 1,289 | 372 | 76 | 3 | 20 | 54 | 1 | 5,354 | 0 | 48 | 16,597 | 11,233 |
| 2011 | 35,301 | 1,345 | 376 | 83 | 0 | 55 | 53 | 0 | 5,531 | 1 | 4 | 16,727 | 11,126 |
| 2012 | 35,851 | 1,429 | 378 | 83 | 3 | 1 | 59 | 0 | 5,940 | 1 | 0 | 16,893 | 11,064 |
| 2013 | 36,100 | 1,331 | 404 | 61 | 6 | 0 | 72 | 1 | 5,467 | 1 | 0 | 17,489 | 11,268 |
| 2014 | 35,815 | 1,571 | 403 | 73 | 4 | 0 | 56 | 0 | 5,974 | 4 | 0 | 16,940 | 10,790 |
| 2015 | 36,172 | 1,659 | 444 | 53 | 2 | 0 | 99 | 0 | 5,605 | 2 | 0 | 17,507 | 10,801 |
| 2016 | 35,859 | 1,604 | 393 | 71 | 1 | 1 | 107 | 0 | 5,195 | 2 | 0 | 17,630 | 10,855 |
| 2017 | 35,535 | 1,552 | 420 | 57 | 0 | 0 | 86 | 0 | 5,334 | 3 | 0 | 17,051 | 11,032 |
| 2018 | 35,376 | 1,589 | 412 | 81 | 2 | 0 | 136 | 0 | 5,527 | 0 | 0 | 17,146 | 10,483 |
| 2019 | 35,703 | 1,690 | 421 | 78 | 1 | 0 | 116 | 1 | 5,439 | 1 | 3 | 17,303 | 10,650 |
| 2020 | 36,139 | 1,364 | 448 | 86 | 0 | 0 | 143 | 0 | 5,354 | 3 | 2 | 17,761 | 10,978 |
| 2021 | 37,792 | 1,544 | 408 | 74 | 0 | 0 | 158 | 0 | 6,051 | 1 | 3 | 18,154 | 11,399 |
| 2022 | 37,375 | 1,440 | 442 | 63 | 0 | 0 | 126 | 0 | 4,865 | 0 | 2 | 18,290 | 12,147 |
| 2023 | 37,576 | 1,453 | 454 | 69 | 0 | 0 | 126 | 0 | 5,409 | 2 | 1 | 18,464 | 11,598 |
| 2024 | 37,236 | 1,674 | 437 | 75 | 0 | 0 | 148 | 0 | 5,389 | 1 | 0 | 17,825 | 11,687 |
| Total | 542,877 | 22,534 | 6,212 | 1,083 | 22 | 77 | 1,539 | 3 | 82,434 | 22 | 63 | 261,777 | 167,111 |

### Open questions added by this amendment

- Whether designed QB runs get their own QB-level rushing effect. Under
  Amendments 6 and 7, designed runs by QBs go in the rush regression with
  team indicators only, so the team's rushing rating absorbs a mobile QB's
  rushing value. When he is out, the team keeps that credit and the backup
  inherits it. One option to evaluate: add a QB indicator to the rush
  regression, give the QB a combined passing and rushing value, and test it
  as an ablation like the QB term in Amendment 6. The other option is to
  leave version 1 as is. This must be settled by its own amendment before
  the as-of-cutoff feature table is built, which is earlier than the first
  model run, because it changes what the regressions contain.
  - Facts (2026-10-07, not a decision): 8,605 designed QB runs in 2010 to
    2024, rising from 3.28% of rush-regression plays in 2010 to 7.15% in
    2024 (peak 7.56% in 2022). The top QBs by designed runs are Newton 690,
    Jackson 611, Hurts 390 and Allen 385. Position comes from the current
    nflverse players table, not the season's role.
- How aborted snaps (1,117 of the 8,605 designed QB runs, 13%, described as
  "Aborted") are treated in any QB rushing effect. This must be settled by
  its own amendment before the as-of-cutoff feature table is built, which is
  earlier than the first model run.

---

## Amendment 8 (2026-10-07, before any model run)

- Aborted plays (settles the open question in Amendment 7, "how aborted
  snaps are treated in any QB rushing effect"): plays with aborted_play = 1
  are excluded from the efficiency plays, which removes them from both
  regressions and from pace. This changes Amendment 7's play set. It also
  removes the 165 aborted plays where nflverse credits the fumble to a
  player other than the QB (164 linemen, 1 wide receiver), about 8 botched
  handoffs to running backs, 127 aborted plays in the pass regressions (the
  QB fumbles the snap, recovers, then throws or is sacked) and 115 aborted
  rushes by non-QBs. These are known losses. One unflagged muffed snap
  (2010_14_SEA_SF, Hasselbeck) stays in. No play-level repair is done. Real
  designed runs fumbled after the QB carried the ball (192 of the 7,488
  unflagged designed QB runs) stay in.
- Evidence recorded: nflverse's aborted_play flag matches the "Aborted" play
  text on all 1,117 designed QB runs with no differences. Aborted plays
  averaged -2.286 EPA against +0.222 for the other designed QB runs. Wilson,
  Tannehill and Fields had the largest aborted shares among the ten QBs with
  the most designed runs (12.2%, 11.4%, 7.8%). A typical starter (200+
  dropbacks) has a median of 6 to 8 designed runs per season, and 16.6% to
  18.7% of them have 20 or more.
- Designed QB runs (settles the open question in Amendment 7): a designed QB
  run is a play with rush = 1 and qb_dropback = 0 whose rusher_player_id is
  listed as a QB in the nflverse players table (the current listing; players
  who changed position are a known limit). The rush regressions get a QB-run
  indicator shared by all QBs, unpenalized, plus a separate indicator for
  each QB, penalized, with its own ridge penalty. QBs with few runs are
  shrunk toward the shared term. Non-QB rushes have no QB term. Scrambles stay
  in the pass regressions.
- Score model inputs: Each QB gets two features: a passing effect from the
  pass-play EPA regression, and a rushing effect equal to his own per-QB
  rushing indicator from the rush EPA regression (the shared QB-run term is
  not a feature), each with its own learned coefficient. When a starter is
  Out, the backup's own effects are used if he has at least 200 dropbacks
  before the cutoff. Otherwise league-average backup effects are used, for
  passing and for rushing, estimated from past games where the starter sat.
  This extends the Features rule to rushing. For Doubtful or Questionable,
  the existing blend by P(plays | status) between the starter's effects and
  the replacement's stays as it is. A starter with no history gets zero for
  both effects.
- Ablation: Test 2 runs a nested ladder of three runs: (1) full, with the QB
  passing and QB rushing terms; (2) without the QB rushing term (the shared
  term and the per-QB indicators removed from the rush regression and as a
  feature), passing term kept; (3) without any QB term (Amendment 6's
  ablation). The passing term is tested first: it stays only if run (2) has
  a smaller prediction error than run (3) by more than the near-tie
  tolerance. The rushing term is tested only if the passing term stays: it
  stays only if run (1) beats run (2) by more than the tolerance. If the
  passing term is dropped, the rushing term is dropped too. In each
  comparison the simpler run wins near-ties. This clarifies Amendment 6's
  ablation, which is the first comparison of this ladder. It is a ladder,
  not a grid.
- Exclusion counts: recompute Amendment 7's exclusion table by reason and
  season with aborted plays added as a reason placed after two-point
  attempts and before null epa. The order of reasons affects the counts.
- Nothing else changes.

### Open questions added by this amendment

Each is settled by its own amendment before the as-of-cutoff feature table
is built.

- The ridge penalty grid for the per-QB rushing indicator, separate from the
  other penalties. It and the Amendment 6 open questions on penalty grids
  and on how a QB's effect carries across seasons must be settled before the
  as-of-cutoff feature table is built.
- How the league-average backup effects (passing and rushing) are
  estimated.
- Whether the QB rushing feature should reflect how often a QB runs, since
  the per-QB indicator measures quality per run and not volume (for scale:
  Jackson and Hurts average about 80 a season, the ten QBs with the most
  designed runs about 40, and a typical starter 6 to 8).

### Evidence: plays with aborted_play = 1

nflverse play-by-play 2010 to 2024, regular season and postseason, cleaned as
in Amendment 5. Each aborted play is placed where Amendment 7's rules would
have sent it. 1,692 aborted plays in total: 328 already outside Amendment 7's
play set, 5 fitting neither regression, and 1,359 newly removed from the
regressions (1,117 designed QB runs plus 242 others).

By play_type:

| play_type | Pass regression | Rush regression | Fits neither | Not in Amendment 7 play set | Total |
|---|---|---|---|---|---|
| extra_point | 0 | 0 | 0 | 6 | 6 |
| no_play | 0 | 0 | 0 | 38 | 38 |
| pass | 127 | 0 | 0 | 34 | 161 |
| punt | 0 | 0 | 0 | 14 | 14 |
| run | 0 | 1,232 | 5 | 236 | 1,473 |
| Total | 127 | 1,232 | 5 | 328 | 1,692 |

By season:

| Season | Pass regression | Rush regression | Fits neither | Not in Amendment 7 play set | Total |
|---|---|---|---|---|---|
| 2010 | 8 | 97 | 0 | 27 | 132 |
| 2011 | 8 | 80 | 0 | 23 | 111 |
| 2012 | 11 | 66 | 1 | 24 | 102 |
| 2013 | 7 | 83 | 0 | 29 | 119 |
| 2014 | 22 | 88 | 0 | 31 | 141 |
| 2015 | 14 | 75 | 1 | 20 | 110 |
| 2016 | 1 | 73 | 0 | 14 | 88 |
| 2017 | 15 | 91 | 0 | 22 | 128 |
| 2018 | 19 | 66 | 0 | 22 | 107 |
| 2019 | 13 | 89 | 1 | 23 | 126 |
| 2020 | 4 | 74 | 1 | 15 | 94 |
| 2021 | 2 | 81 | 0 | 25 | 108 |
| 2022 | 1 | 96 | 0 | 16 | 113 |
| 2023 | 1 | 82 | 1 | 14 | 98 |
| 2024 | 1 | 91 | 0 | 23 | 115 |
| Total | 127 | 1,232 | 5 | 328 | 1,692 |

### Exclusion counts by reason and season (replaces Amendment 7's table)

Same data, candidate plays and method as Amendment 7's table, with aborted
plays added as a reason after two-point attempts and before null epa.
Reasons are applied in the column order below, and each play is counted
once, under the first reason it meets. The order of reasons affects the
counts: for example, aborted plays that are also two-point attempts are
counted as two-point attempts, and aborted plays in garbage time are counted
as aborted plays.

| Season | Candidate plays | no_play | kneel | spike | other play_type | pass=0 and rush=0 | two-point attempt | aborted play | null epa | garbage time | fits neither regression | dropback, blank passer_id | kept: pass regression | kept: rush regression |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2010 | 35,047 | 1,289 | 372 | 76 | 3 | 20 | 54 | 123 | 1 | 5,336 | 0 | 48 | 16,589 | 11,136 |
| 2011 | 35,301 | 1,345 | 376 | 83 | 0 | 55 | 53 | 105 | 0 | 5,514 | 1 | 4 | 16,719 | 11,046 |
| 2012 | 35,851 | 1,429 | 378 | 83 | 3 | 1 | 59 | 95 | 0 | 5,923 | 0 | 0 | 16,882 | 10,998 |
| 2013 | 36,100 | 1,331 | 404 | 61 | 6 | 0 | 72 | 113 | 1 | 5,444 | 1 | 0 | 17,482 | 11,185 |
| 2014 | 35,815 | 1,571 | 403 | 73 | 4 | 0 | 56 | 135 | 0 | 5,949 | 4 | 0 | 16,918 | 10,702 |
| 2015 | 36,172 | 1,659 | 444 | 53 | 2 | 0 | 99 | 106 | 0 | 5,589 | 1 | 0 | 17,493 | 10,726 |
| 2016 | 35,859 | 1,604 | 393 | 71 | 1 | 1 | 107 | 85 | 0 | 5,184 | 2 | 0 | 17,629 | 10,782 |
| 2017 | 35,535 | 1,552 | 420 | 57 | 0 | 0 | 86 | 125 | 0 | 5,315 | 3 | 0 | 17,036 | 10,941 |
| 2018 | 35,376 | 1,589 | 412 | 81 | 2 | 0 | 136 | 102 | 0 | 5,510 | 0 | 0 | 17,127 | 10,417 |
| 2019 | 35,703 | 1,690 | 421 | 78 | 1 | 0 | 116 | 121 | 1 | 5,421 | 0 | 3 | 17,290 | 10,561 |
| 2020 | 36,139 | 1,364 | 448 | 86 | 0 | 0 | 143 | 93 | 0 | 5,340 | 2 | 2 | 17,757 | 10,904 |
| 2021 | 37,792 | 1,544 | 408 | 74 | 0 | 0 | 158 | 108 | 0 | 6,026 | 1 | 3 | 18,152 | 11,318 |
| 2022 | 37,375 | 1,440 | 442 | 63 | 0 | 0 | 126 | 111 | 0 | 4,851 | 0 | 2 | 18,289 | 12,051 |
| 2023 | 37,576 | 1,453 | 454 | 69 | 0 | 0 | 126 | 96 | 0 | 5,397 | 1 | 1 | 18,463 | 11,516 |
| 2024 | 37,236 | 1,674 | 437 | 75 | 0 | 0 | 148 | 114 | 0 | 5,367 | 1 | 0 | 17,824 | 11,596 |
| Total | 542,877 | 22,534 | 6,212 | 1,083 | 22 | 77 | 1,539 | 1,632 | 3 | 82,166 | 17 | 63 | 261,650 | 165,879 |

---

## Amendment 9 (2026-10-08, before any model run)

- Correction to Amendment 8: its order-of-reasons sentence gives two examples.
  The garbage-time example is right (268 aborted plays are counted as aborted
  plays). The two-point example illustrates nothing, because there are 0
  aborted plays that are also two-point attempts
  (research/aborted_two_point_check.py). Read that sentence as having the
  garbage-time example only. Nothing else in Amendment 8 changes.

- Penalty units (settles the open question "the ridge penalty grid for the QB
  indicator, separate from the team penalty"): every ridge penalty is in units
  of recency-weighted plays, meaning a penalty of L pulls an indicator toward
  zero as if it had L plays of zero effect behind it. The intercept, the
  home-field term and the shared QB-run term (Amendment 8) are not penalized.

- Four penalties, each from its own grid, tuned separately for each recency
  half-life (4, 8, 16):
  - Pass regressions: team penalty (offense and defense indicators) from {100,
    300, 1000, 3000}, and QB passing indicator penalty from {100, 300, 1000,
    3000}. All 16 combinations are tried.
  - Rush regressions: team penalty from {100, 300, 1000, 3000}, and per-QB
    rushing indicator penalty from {25, 100, 400, 1600}. All 16 combinations
    are tried.
  - The success-rate regressions reuse the penalties chosen for the EPA
    regressions. They are not tuned separately.

- Who chooses the penalties (replaces one sentence of Amendment 5, "Ridge
  strength is chosen in walk-forward validation from a predefined grid"):
  ridge strengths are not chosen in test 2. They are chosen once, by the
  tuning procedure below, and then frozen. Test 2 keeps every other choice
  that earlier rules give it: the lookback, the recency half-life, the
  early-season fade length, additive vs multiplicative form, the QB ablation
  ladder (Amendments 6 and 8) and the key-starters-out check. When test 2 uses
  a half-life, it uses the penalties tuned for that half-life.

- Rating window (keeps Amendment 5's split): the rating regressions use all
  play-by-play from 2010 up to the cutoff, with recency weights and no
  lookback cut. Test 2's lookback (3, 5, 8 seasons, cut off at 2013) applies
  only to the games used to train the score model. The rating history is every
  game finished before the cutoff (kickoff plus 4 hours), on any weekday, with
  neutral-site and playoff games included. The home-field term is 0 for
  neutral-site games.

- Tuning procedure: for each Thursday, Sunday and Monday regular-season game
  that is not neutral-site (the version 1 games) in 2014 to 2017, fit as of
  that game's own cutoff (Amendment 4 rule), with no early-season fade, and
  predict the EPA of every efficiency play in that game (Amendment 8 play set)
  from the fitted indicators and the game's own home-field term. Games that
  share a cutoff share one fit. Games outside version 1 are never predicted.
  The error is the mean squared error over those held-out plays, pooled over
  the four seasons, with equal weight per play. For each half-life and each
  regression type the smallest error wins. A choice within 0.1% (relative) of
  the smallest error goes to the larger penalty. If the winner sits at the
  edge of a grid, it is reported and the grid is not extended.
  - Seasons 2018 to 2024 and the 2025 holdout are never used for penalty
    tuning. No game result or betting line is used.

- Order against test 1: test 1 (leakage) runs with fixed penalties of 1000 for
  the team, 1000 for the QB passing indicator and 400 for the per-QB rushing
  indicator, for every half-life, because leakage does not depend on those
  values. Tuning runs only after test 1 passes. The tuned values replace the
  fixed ones from test 2 onward.

- QB effects across seasons (settles "how a QB's effect carries across
  seasons"): each QB has one passing indicator and one rushing indicator for
  the whole rating history, not one per season and not one per team. His games
  are weighted by the same recency weights (games ago) as everything else. The
  model is refit at every cutoff from scratch.

- League-average backup (keeps the wording in Features and Amendment 8,
  "estimated from past games where the starter sat", and settles how it is
  estimated): a game where the starter sat is a game in which the team's
  season leader had no dropbacks. The season leader is the QB with the most
  dropbacks for that team in that season (counted up to the cutoff for the
  current season). "Season leader" is a label for this estimate only. Who
  starts on a given Sunday is decided by a later amendment on starter status.
  The league-average backup passing effect is the dropback-weighted mean of
  the fitted passing indicators of the QBs who threw in those games, weighted
  by their dropbacks in those games. The league-average backup rushing effect
  is the mean of their fitted rushing indicators with the same weights. Both
  are re-estimated at every cutoff from the same fit. Known limit: ridge
  shrinks low-sample backups toward zero, so this average sits closer to zero
  than the true backup gap.

- Open questions: this amendment settles the penalty grids, the tuning
  procedure, the carry-over across seasons and the league-average backup
  estimation. Every other open question from Amendments 6 to 8 stays open.
  - Team indicators and the early-season fade: whether team offense and
    defense indicators are one per team over the whole rating history (recency
    weights only) or one per season, and what the early-season fade in
    Amendment 5 then acts on. Must be settled by its own amendment before the
    as-of-cutoff feature table is built. Penalty tuning and test 2 both use
    this definition.

---

## Amendment 10 (2026-10-10, before any model run)

- Team indicators (settles the open question in Amendment 9 titled "Team indicators and the early-season fade"): in the pass and rush regressions, for both EPA and success rate, the offense and defense indicators are one per team per season (a team-season), not one per team over the whole history. All team-season indicators are fit together over the whole rating history (Amendment 9), with the same recency weights and the ridge penalties from Amendment 9. QB indicators stay one per QB over the whole history. The intercept, the home-field term and the shared QB-run term are unchanged.

- Early-season blend (settles what the early-season fade acts on; keeps the fade lengths and the prior-season-end idea of Amendment 5): for a team in season S with g games finished before the cutoff in season S, each of its 8 team ratings (pass offense, pass defense, rush offense and rush defense, each for EPA and for success rate) is w x current + (1 - w) x c x prior.
  - Current is the team's season S indicator from the fit at that cutoff.
  - Prior is the team's season S-1 indicator from the end-of-season fit for S-1. The end-of-season fit for S-1 uses every game finished at or before the finish time of the last regular season game of season S-1 (kickoff plus 4 hours, so that last game is included), and no playoff game of season S-1. It is made with the same half-life, the same penalties and the same ablation run as the fit it is used in, so it is recomputed under each setting being run and is not stored from another setting.
  - w = min(1, g / F), where F is the fade length (4, 8 or 12 games, chosen in test 2). At g = F or more the prior no longer counts.
  - c is a carry factor. A team with no season S-1 indicator uses 0 for prior.

- Carry factor c: one value for each of the 8 rating types, for each half-life and for each ablation run (the full run; the run without QB rushing; the run without any QB term), estimated once and then frozen. For each season pair S, S+1 with S from 2010 to 2016, take each team's season S+1 indicator from the end-of-season fit for S+1, and its season S indicator from the end-of-season fit for S, both made with that setting's regressions and penalties. Regress the first on the second, through the origin, over all 32 teams, pooling the 7 pairs (224 team pairs) for one regression per rating type. Seasons 2018 and later are never used. c is estimated after the penalty tuning in Amendment 9, using the tuned penalties for that half-life (the success-rate regressions use the EPA penalties, as in Amendment 9). The two ablation runs reuse the team penalties tuned for the full run and are not re-tuned, and each estimates its own c.

- Fixed values for test 1 and for penalty tuning: test 1 runs with c = 0.5 for all 8 rating types and F = 8. The penalty tuning in Amendment 9 predicts each game with the same blend, with c = 0.5 and F = 8 fixed, and with the prior recomputed under each penalty combination being tried. This replaces the words "no early-season fade" in the Amendment 9 tuning procedure and changes nothing else there.

- QB rushing feature (replaces the QB rushing feature in the "Score model inputs" bullet of Amendment 8, and clarifies the sentence about "zero for both effects" in that bullet; nothing else in the bullet changes): a QB's rushing feature is V x (S + b). S is the shared QB-run term and b is his per-QB rushing indicator, both from the same fit. The feature is in EPA per game and has its own learned coefficient. The QB passing feature is unchanged. The ablation ladder is unchanged, and "without QB rushing" removes this feature.
  - V is his recency-weighted designed QB runs per game. It counts only the designed QB runs in the Amendment 8 play set (the runs his per-QB indicator is fit on). It covers only games in which he had at least one dropback: a game with no dropbacks adds neither runs nor weight. Each game's weight is the recency weight its plays carry in the fits at that cutoff.
  - A backup with at least 200 dropbacks before the cutoff uses his own V and b.
  - The league-average backup (Amendment 9) uses the league-average backup V times (S + the league-average backup b). The league-average backup V is the mean of V over the QBs who threw in the starter-sat games used for the league-average backup, weighted by their dropbacks in those games.
  - "No history" means no dropbacks before the cutoff. A starter with no history gets b = 0 and V equal to the mean of V over all QBs in the rating history, weighted by recency-weighted dropbacks. In Amendment 8, "zero for both effects" means the two indicators are zero (the passing indicator and b). The rushing feature is then as described here and is not itself zero.
  - Doubtful and Questionable blends work as in Amendment 8.

- Open questions: this amendment settles the team-indicator and early-season fade question and the QB rushing volume question. Every other open question stays open.

---

## Amendment 11 (2026-10-10, before any model run)

- Scope (settles the starter status and "key starters out" items that the original Features section and Amendment 5 left unsettled, and the statement in Amendment 9 that who starts on a given Sunday is decided by a later amendment): the rules below say who the primary QB is, how the report is read, how the QB features are blended, and what a key starter is.

- Report status as of the cutoff: for a team and game, a player's status is the row for that player and week with report_status Out, Doubtful or Questionable whose date_modified is at or before the game's cutoff (Amendment 4). If a player has more than one row for the week, the row with the latest date_modified at or before the cutoff is used. A row stamped after the cutoff is ignored. Rows with Probable, Note or blank, and players with no row, have no status. For 2010 to 2020, where the time zone of date_modified is unknown (Amendment 3), stamps are read as Pacific clock time (the worst case), so a late stamp is never counted as early. 2021 to 2024 are read as UTC converted to Eastern. Seasons from 2025 are outside this amendment.

- Who counts as a QB: in the rules of this amendment, a QB is a player listed as QB in the nflverse players table, or a player recorded as a team's starting QB (home_qb_id or away_qb_id) in a game finished before the cutoff. The second part is needed because 20 starts in 2010 to 2024 belong to players listed elsewhere (Terrelle Pryor 10, Taysom Hill 9, Kendall Hinton 1). A QB's dropbacks are counted by passer_id (Amendment 7). Known limit: Amendment 8's designed-run rule still uses the players-table position, so the designed runs of those players are in the non-QB rush term.

- Primary QB (this is a different thing from the "season leader" label in Amendment 9, which is only used to estimate the league-average backup):
  - The primary QB is the QB who started the team's most recent finished game (nflverse home_qb_id or away_qb_id of that game). A game is finished 4 hours after kickoff. Regular season and playoff games both count.
  - Exception to the Features line that starting QBs are never model inputs: the home_qb_id and away_qb_id of games finished before the cutoff may be used for the primary QB rule and for the "Who counts as a QB" definition in this amendment, and for nothing else, because who started a finished game is a past fact at the cutoff. The ids of the game being predicted and of later games are never used as model inputs. They stay available to the ceiling tests only.
  - In the first game of a season, the primary QB is the QB with the most dropbacks for the team in its previous regular season.
  - Returning starter: if a QB on the team's report has status Questionable or Doubtful, and he had the most dropbacks of any of the team's QBs over its last 16 finished regular season games, he is the primary QB instead.
  - Known limit: offseason QB changes are invisible in the first game of a season, and a starter returning from injury with no status row is missed.

- Substitute QB: when the primary QB is not expected to play, the substitute is the QB with the most dropbacks for the team over its last 8 finished regular season games, not counting the primary QB and skipping any QB whose status is Out. If there is no such QB, the league-average backup of Amendment 9 is used. Amendment 8's 200-dropback rule then applies: a substitute with at least 200 dropbacks before the cutoff uses his own effects, otherwise the league-average backup is used.

- Status of the primary QB: Out means he is replaced by the substitute (probability 0 that he plays). No status means he plays. Doubtful and Questionable use P(plays | status).
  - P(plays | status) is the share of past primary QBs with that exact status, in regular season games, who had an offense snap share of at least 0.5 in that game (nflverse snap counts, offense_pct). It is estimated separately for Doubtful and for Questionable, pooled over all regular seasons from 2013 up to the season before the one being predicted. It is never estimated from the season being predicted or later.
  - This is an exception to the Features wording "calibrated on training seasons": P is not limited to the test 2 lookback, because it calibrates a status and not a model fit.
  - It needs at least 2 prior seasons of snap counts, so it is available from the 2015 season. A game in 2013 or 2014 in which either team's primary QB has status Doubtful or Questionable is excluded from the score model's training games (the whole game) and counted in the file. Test seasons (2018 and later) are never affected.
  - The QB features (the passing feature and the rushing feature of Amendment 10) are blended: P x the primary QB's feature + (1 - P) x the substitute's feature.

- Key starters (settles what counts as a key starter), for non-QB players:
  - Snap shares come from the nflverse snap counts and are linked to injury rows by player ID through the nflverse players table.
  - A player appears in a game if he has at least one offense or defense snap. A row with 0 offense and 0 defense snaps (special teams only) is not an appearance.
  - Take the team's last 8 finished regular season games. A player is a key starter if he appeared in at least 3 of them and his average snap share over the games he appeared in is at least 0.75 on offense or at least 0.75 on defense. The larger of the two decides his side. Special teams are ignored.
  - A key starter counts as out if his status is Out or Doubtful. Questionable does not count.
  - A team with fewer than 3 finished games with snap counts before the cutoff (2013 only) gets a value of 0, and those team-games are counted in the file.
  - The feature follows the Features section, "player weights from pre-cutoff snap share": the value out is the sum of the average snap shares (as defined above) of the key starters counted as out. There are two features per team and game: its own offensive value out, and the opponent's defensive value out. Each has its own learned coefficient, shared across home and away.
  - Test 2 runs once with these two features and once without them. They are kept only if the run with them has a smaller prediction error by more than the near-tie tolerance, as with the QB ablation in Amendments 6 and 8. This is one extra comparison, not a new grid. The tolerance is set by its own amendment before test 2 runs.

- Open questions:
  - The source for the primary QB in the first game of a season (whether any nflverse roster or depth chart source can be shown to be stamped before the cutoff). Until it is settled, the rule above applies.
  - The Features section says "Also a flag in the betting filter" for key starters out. That flag is not defined here, and it is not part of the key starters feature. Whether the bets in test 6 and test 7 go through such a flag is added here as a new open question.
  - The injury timing rule for 2025 and 2026 (nflverse has no injury timestamps for those seasons). It must be settled before the 2025 holdout.
  - The near-tie tolerance and the prediction error metric stay open and also govern the key-starters ablation.
  - Every other open question stays open.

- Checks before writing (read-only, 2026-10-10, no model run):
  - Schedules 2010 to 2024: 3,903 regular season games; home_qb_id and away_qb_id have 0 nulls and 0 blanks.
  - Injuries 2010 to 2024: columns gsis_id, position, report_status and date_modified exist; 1,028 regular season QB rows with status Out, Doubtful or Questionable (Out 490, Questionable 446, Doubtful 92), none with a null gsis_id.
  - Snap counts 2013 to 2024: columns offense_pct and defense_pct (scale 0 to 1); player ID pfr_player_id, linking to pfr_id in the nflverse players table; 284,915 of 285,080 regular season rows map to a gsis_id (99.94%); QB rows 7,749 of 7,749. The 2012 snap count file is empty.
  - Starting QBs 2010 to 2024, regular season and playoffs: 8,156 team-game starts, 20 of them by players not listed as QB in the players table (Terrelle Pryor 10, Taysom Hill 9, Kendall Hinton 1).

---

## Amendment 12 (2026-10-15, before any model run)

- Purpose. Settles the open items that block the as-of-cutoff feature table, the conflict about frozen settings tuned on later data, and the definition of test 1. Written after the feature table plan and a read-only check of data facts, before any feature code exists and before any model result.

- Facts checked (read-only; no scores, margins, ratings or model results were looked at):
  - a. In the nflverse schedules file, gametime is a 24-hour HH:MM text field, present and well formed for all 4,635 games from 2010 to 2026. Twenty-nine games in 2026 have a stored ESPN kickoff. For 14 of them (the 2026-10-04 test fixture), each game was matched by ESPN id and gametime read as US Eastern equals the ESPN kickoff in all 14. For the other 15 (13, 1 and 1 games on three dates, stored by date without team labels), the set of kickoff times for each date equals the nflverse set for that date; a game-by-game match was not possible. No ESPN kickoff is stored for any game before 2026, so the match is not verified for earlier seasons.
  - b. The schedules weekday column equals the weekday computed from gameday for all 3,903 regular season games from 2010 to 2024.
  - c. 2011_13_DET_NO was played on Sunday 2011-12-04 with gametime 20:20, as a regular season home game for NO. It is a version 1 game.
  - d. Schedules home_rest and away_rest are never missing, but they differ from the calendar days between a team's consecutive games in the same season in 34 of 7,326 pairs (12 in 2019, 20 in 2021, 2 in 2022).
  - e. Schedules roof holds outdoors, dome, closed, open, and a blank for 34 unplayed 2026 games. Open and closed occur only at the stadium_id values ATL97, DAL00, HOU00, IND00, PHO00 and RIO00. No stadium_id shows both dome and outdoors.
  - f. Play-by-play uses the 32 current team codes in every season from 2010 to 2024. Snap counts and injuries still use SD, STL and OAK in early seasons (last seen in both: SD 2016, STL 2015, OAK 2019) and use none of them from 2020 on.

- Decisions:
  - 1. Kickoff and finish [F1]. A game's kickoff is its nflverse schedules gameday plus gametime, read as US Eastern local time (America/New_York, with daylight saving applied by date). Its finish is kickoff plus 4 hours. This is the kickoff source for every game from 2010 on in the backtest. Limit: nflverse overwrites schedule fields after the fact, and no ESPN kickoff is stored for games before 2026, so gametime is the last recorded scheduled kickoff and is not proof of what was known at a cutoff. Live use keeps the ESPN kickoff, as the live system does.
  - 2. Before or at the cutoff [F2]. A game feeds a prediction only if its finish is strictly before the cutoff. A game finishing exactly at a cutoff is not used. This applies wherever these rules say "finished before the cutoff" or "not finished by its cutoff", including test 1. The wording "at or before" stays where it appears for different quantities: injury report rows stamped at or before the cutoff (Amendment 11), and the end-of-season fit, which includes every game finished at or before the finish of the last regular season game of the prior season (Amendment 10).
  - 3. Weekday [F3]. Weekday is computed from gameday. The schedules weekday column is not used.
  - 4. 2011_13_DET_NO [F4]. It remains a version 1 game by definition, and it stays excluded from features and training as Amendment 5 says: its plays are in no fit, and it gets no feature row and no training row. For every other purpose it counts as a finished game that was played: game-weeks and age (decision 5), g, rest days, bye flags, the last 8 and last 16 game windows, the primary QB (from its schedule starting QB ids), and snap-count appearances. Its dropbacks are absent from dropback counts because its plays are not kept. The cutoff and finish table is built from the schedules file, not from the derived games file, so that this game is in it, with a column marking it.
  - 5. Age of a game, "games ago" [F5]. Number every NFL game-week in time order from 2010 week 1: each distinct (season, week) pair, regular season and playoff weeks alike, ordered by the earliest gameday among its games, gets the next whole number n. For a game being predicted in game-week P, a play from a game in game-week Q has age n(P) - n(Q). A game in the same week that finished before the cutoff has age 0, and last week's games have age 1. The recency weight is 0.5 to the power (age / H), where H is the half-life (4, 8 or 16). The age is the same for every team and for both sides of the ball. Byes, neutral-site games and playoff weeks count as weeks; a cancelled game adds no week. The build stops with an error if an age is negative for a game that finished before the cutoff. Every place in these rules that says "games ago" or "recency weights" (rating fits, pace, V, recency-weighted counts) uses this age. The count g in Amendment 10 is unchanged: the number of the team's own regular season games in the season that finished before the cutoff.
  - 6. Pace [F6]. A team's pace is its offensive plays per game: for each game the team has played, the number of its plays in the kept pass and run play set (Amendments 7 and 8, so garbage-time plays are not counted); then the mean over the team's games from 2010 that finished before the cutoff, weighted by each game's recency weight (decision 5). A game with no kept plays (only 2011_13_DET_NO) is left out of the mean; it is not counted as a game with zero plays. Pace is not blended with the prior season. Both teams' paces are features.
  - 7. Dropback counts [F7]. Every dropback count and threshold counts rows of clean_plays.parquet with qb_dropback = 1, by passer_id. These are kept plays only, so garbage-time and other excluded dropbacks do not count. This covers the 200-dropback rule, the season leader, the first-game primary QB, the returning starter, the substitute, the league-average backup weights, and V's "at least one dropback".
  - 8. Who is a QB [F8]. Amendment 11's definition of a QB governs every rule that selects or counts a QB: the season leader, primary QB, substitute, returning starter, the "QBs who threw in those games" of the league-average backup, and the "all QBs in the rating history" of Amendment 10 (which here means QBs by Amendment 11's definition with at least one kept dropback in a game finished before the cutoff; the weighting stays as Amendment 10 says). Rating-fit indicators (Amendment 9) still exist for every passer_id with kept plays.
  - 9. League-average backup pool [F9]. This keeps Amendment 9's definition of the season leader (the QB with the most kept dropbacks for the team in the season, counted up to the cutoff for the current season and over the whole regular season for completed seasons) and adds the pool. For a prediction at cutoff C, the pool is every regular season team-game from 2010 whose game finished strictly before C (no playoffs; any weekday or site) in which that team's season leader, as just defined and as of C, had no kept dropbacks. The league-average backup is the mean of the fitted indicators (from the fit at C) of the QBs (decision 8) who had kept dropbacks in those team-games, each weighted by his kept dropbacks in them. No recency weights are used. The build stops with an error if the pool is empty.
  - 10. Ties [F10]. Where a rule picks the QB with the most dropbacks and QBs tie (season leader, first-game primary QB, returning starter, substitute): the QB whose latest finished game with a kept dropback is more recent wins; if still tied, the smaller gsis_id compared as text wins. For a key starter, if the offense and defense snap shares are equal, the offense share is used.
  - 11. P(plays | status) [F11]. The pool is version 1 games only, from 2013 through the season before the prediction's season. For each such game and team, take the team's primary QB (Amendment 11) and his status at that game's cutoff. Among those with the status in question (Doubtful or Questionable), P is the share whose offense snap share in that game was at least 0.5. A primary QB with no snap-count row for the game counts as not playing (share 0). Snap rows that could not be linked to a player id (Amendment 11) count as absent.
  - 12. Rest, short week, bye [F12]. Rest is the number of calendar days from the team's previous game in the same season to this game, computed from gameday. A cancelled game does not count as a game. For a team's first game of a season, rest is the value in the schedules file. Short week (Amendment 5) means rest of 5 days or fewer. The bye flag is 1 when the team's previous game in the same season was two or more schedule weeks earlier, and 0 otherwise, including for a team's first game of a season. The schedules home_rest and away_rest are not used otherwise; a difference from them is not an error.
  - 13. Roof category [F13]. The roof category of a version 1 game is a fixed attribute of its stadium_id. Retractable: ATL97, DAL00, HOU00, IND00, PHO00. Dome: ATL00, BUF01, DET00, LAX01, MIN00, MIN01, NOR00, STL00, VEG00. Outdoors: every other stadium_id that hosted a version 1 game from 2010 through 2024 (the build lists them in its report). The feature build does not read the schedules roof column, so game-day open and closed values and blank roof values are never used. A version 1 game at a stadium_id in none of these three groups stops the build with an error, so a new stadium gets classified by amendment.
  - 14. Time zones [F14]. Home time zone by team, using current codes: America/New_York: ATL, BAL, BUF, CAR, CIN, CLE, DET, IND, JAX, MIA, NE, NYG, NYJ, PHI, PIT, TB, WAS. America/Chicago: CHI, DAL, GB, HOU, KC, MIN, NO, TEN, and LA through 2015. America/Denver: DEN. America/Phoenix: ARI. America/Los_Angeles: LAC, LV, SEA, SF, and LA from 2016. For a version 1 game the game site's zone is the home team's zone, the home team's shift is 0, and the away team's shift is the home team's UTC offset on the game date minus the away team's home-zone UTC offset on the game date, in hours (positive means the away team travelled east). Arizona keeps UTC-7 all year. This is not checked in this amendment: the build report lists every version 1 game whose stadium_id differs from the home team's most common stadium_id that season. The list is a report, not an error.
  - 15. Team codes [F15]. Snap counts and injuries are mapped through features/ids.py (STL to LA, SD to LAC, OAK to LV) when loaded, before any join. The current code set is: ARI, ATL, BAL, BUF, CAR, CHI, CIN, CLE, DAL, DEN, DET, GB, HOU, IND, JAX, KC, LA, LAC, LV, MIA, MIN, NE, NO, NYG, NYJ, PHI, PIT, SEA, SF, TB, TEN, WAS. Loading any source stops with an error on a code outside this set after mapping. The check covers home_team and away_team on every play-by-play row, posteam and defteam on the kept pass and run plays, and the team columns of schedules, snap counts and injuries; none of these may be blank. A blank posteam or defteam on a row outside the kept play set is ignored. The existing loaders do not yet make this check; it is added when the table is built.
  - 16. Rescheduled games [W5]. A game's cutoff, kickoff and finish come from its final gameday and gametime. The originally scheduled date is not used.
  - 17. Snap rows and teams [W6]. Key starter appearances and snap shares (Amendment 11) use only snap rows whose team is the team in question, from that team's own last 8 finished regular season games. Snap rows that could not be linked to a player id are ignored.
  - 18. Null win probability [W4]. Plays with a null wp stay in the play set, as the build does today (a null never meets the garbage-time test).
  - 19. Feature table layout [W7]. One row per version 1 game, except 2011_13_DET_NO (decision 4). Team-level features appear twice, with home_ and away_ prefixes: the 8 blended team ratings, pace, the QB passing and rushing features, the primary and substitute QB ids and P, the key-starter values as Amendment 11 orients them, rest, short week, bye flag, and time-zone shift. Game-level facts appear once: game_id, season, week, group, primetime, division game, roof category, neutral flag.
  - 20. Frozen settings versus the finished-before-cutoff rule [S9]. The tuned ridge penalties (Amendment 9) and the carry factors c (Amendment 10) are fixed settings, not game data, so the rule that features use only games finished before the cutoff does not apply to them. They are chosen using only data through 2017 (penalties: version 1 games in 2014 to 2017; carry factors: season pairs through 2016-2017). Every game scored in test 2 (2018 on) and in tests 3 to 7 comes after all of that data. Known cost: features of training games in 2013 to 2017 use settings chosen with data from the same period, so those training rows are slightly flattered. No scored game is affected. Test 1 does not test this, because it runs with fixed values.

- Test 1 definition [F16 to F20]:
  - 21. Games. Every version 1 game from 2013 to 2024.
  - 22. Settings. Each of the three half-lives (4, 8, 16) and each of the three ablation runs (full; without QB rushing; without any QB term). Fixed values: team penalty 1000 (pass and rush), QB passing penalty 1000, per-QB rushing penalty 400, the success regressions reusing them, c = 0.5 and F = 8.
  - 23. The deleted build. The feature build reads only these columns of the schedules file: game_id, season, week, game_type, gameday, gametime, home_team, away_team, location, stadium_id, div_game, home_rest, away_rest, home_qb_id and away_qb_id. It reads home_qb_id and away_qb_id only for games finished strictly before the cutoff. For each tested game G with cutoff C, rebuild G's feature row from copies of the input tables with these changes: (a) remove the plays and snap-count rows of every game not finished strictly before C, including G and any game of G's week that has not finished; (b) in the schedules file, keep only the columns listed above (including game_id), and set home_qb_id and away_qb_id to missing for every game not finished strictly before C; (c) remove injury rows stamped after C, and all injury rows for weeks after G's week. Tables built from past games (the P(plays | status) pool, the league-average backup pool, the end-of-season fits) are rebuilt from the reduced tables. Static facts (players table, stadium lists, time zone table, code map) are not reduced.
  - 24. Pass. For every tested game and setting, every column of G's feature row from the deleted build is compared with the full build. Text, id and flag columns must be equal. Numeric columns must satisfy |a - b| <= 1e-8 x max(1, |a|). A missing value must be missing in both. Any difference fails test 1. After a failure, the code is fixed and the whole test is rerun from scratch. A fix that needs a rule change needs a new amendment first. This tolerance and this comparison are not changed after a result.

- Still open after this amendment:
  - Before test 2: the prediction error metric; the near-tie tolerance and which option wins when "simpler" and "middle" point to different choices; how test 2's choices are searched (full grid or fixed order, and one choice for all of 2018 to 2024 or one per season); additive versus multiplicative form; score model regularization; which games train the score model; first-half score reconciliation; the QB passing penalty in the "without QB rushing" run.
  - Later: injury timing and the cutoff table for 2025 and 2026; the first-game primary QB source; the key starters flag in the betting filter; the error spread; test 3 significance; the 2025 holdout training window; the Kalshi price at the cutoff; test 5 seasons; test 6 liquidity thresholds; ceiling test seasons and metric; the minimum number of flagged bets; the meaning of "the freeze"; first-half baselines.
  - Unverified: that nflverse gametime for seasons before 2026 equals the scheduled kickoff known at the time; that every version 1 game was played in its home team's time zone.

---

## Amendment 13 (2026-10-15, before any model run)

- Purpose. Settles two points the rating fit needs before it is built. Written before any fit has been run.

- Decisions:
  - 1. Home-field term coding. In every regression (pass EPA, pass success, rush EPA, rush success) the home-field term is one coefficient, shared by the offense and defense sides, and it is not penalized (Amendment 9). On each play its value is +1 if the offense is the home team, -1 if the offense is the away team, and 0 if the game is at a neutral site (schedules location Neutral). The intercept is not penalized. A neutral-site game therefore sits halfway between a home and an away game, which is what Amendment 9 means by "the home-field term is 0 for neutral-site games".
  - 2. Ages in the end-of-season fit. The end-of-season fit for season S-1 (Amendment 10) measures play ages as in Amendment 12 decision 5, with the predicted game-week P taken to be the game-week of the last regular season game of season S-1. The last regular season games of S-1 therefore have age 0. The end-of-season fit does not change with the game it is later used for, and it uses the same half-life as the current fit. The carry factor estimate of Amendment 10 uses these same fits.
  - 3. Fit inputs. A rating fit is a function of the as-of time and the predicted game-week P. Every version 1 cutoff belongs to exactly one game-week (all 715 version 1 cutoffs were checked), so games that share a cutoff (Amendment 9) share one fit.

---

## Amendment 14 (2026-10-17, before any model run)

- Purpose. Settles eight points the QB features (plan module 9) need before they are built. Written before any QB feature code exists and before any model result.

- Decisions:
  - 1. Substitute in every row. The substitute QB (Amendment 11) is computed and filled for every row, including rows where the primary QB has no status (P = 1), using the Amendment 11 rule unchanged (the most kept dropbacks for the team over its last 8 finished regular season games, not counting the primary QB, skipping any QB whose status is Out; the league-average backup if there is no such QB; the 200-dropback rule of Amendment 8). Amendment 11 already excludes the primary QB ("not counting the primary QB"). Each blended QB feature is P x the primary QB's feature + (1 - P) x the substitute's feature in every row; where P is missing (decisions 2 and 3), the blended features are missing.
  - 2. 2013 and 2014. A 2013 or 2014 row whose primary QB has status Doubtful or Questionable keeps its row in the table. P and both blended QB features (passing and rushing) are missing. P is not treated as 1. Every other column of the row is filled. The training-exclusion flag of Amendment 11 is set; since Amendment 11 excludes the whole game, the flag is set on both teams' rows of that game.
  - 3. Empty P pool. If the pool of Amendment 12 decision 11 has zero cases for the status of a row's primary QB (Doubtful or Questionable), P is missing for that row, its blended QB features are missing, the game gets the same training-exclusion flag, and the build does not stop. A separate column gives the reason a row is flagged: before 2015 (decision 2) or empty pool (this decision). The build reports the pool size by status and by season. Any minimum pool size is settled by amendment before test 2.
  - 4. No rushing indicator. A QB with kept dropbacks but no per-QB rushing indicator in the fit has b = 0. In the league-average backup rushing mean (Amendment 9; Amendment 12 decision 9) he counts with b = 0 and his dropback weight; he is not left out.
  - 5. Tie-break (refines Amendment 12 decision 10). The "latest finished game with a kept dropback" compared between tied QBs must be a game of this team inside the window of the rule being applied: the last 8 finished regular season games for the substitute, the previous regular season for the first-game primary QB, the last 16 finished regular season games for the returning starter, and the team's season (up to the cutoff for the current season) for the season leader. If still tied, decision 10's final tie-break applies (the smaller gsis_id compared as text).
  - 6. Ablation runs. Under the run without any QB term, the QB passing and QB rushing feature columns are absent from the table (not zero). Under the run without QB rushing, only the QB rushing feature columns are absent. The primary and substitute QB ids, P, the training-exclusion flag and its reason are computed in every run and must be identical across all three runs and all three half-lives; the build checks this.
  - 7. Substitute with a status. A substitute with status Doubtful or Questionable is used at full weight (1 - P), with no further blend. The build reports how many rows have one.
  - 8. Real-data build. The QB feature table is built for all 9 combinations (half-lives 4, 8, 16 x the three ablation runs) with the test 1 values (team penalty 1000, QB passing penalty 1000, per-QB rushing penalty 400, c = 0.5, F = 8). Row counts must match across the 9, and the ids, P and flags must be identical.

- Open questions added by this amendment (each settled before test 2):
  - Whether rows with missing P are scored in test 2.
  - Any minimum pool size for P.

---

## Amendment 15 (2026-10-17, before any model run)

- Purpose. Settles three points the key starters features (plan module 10) need before they are built. Written before any key starters code exists and before any model result. The key starters rule itself stays as Amendment 11 and Amendment 12 decisions 10 and 17 state it: the team's own last 8 finished regular season games; at least 3 appearances; an average snap share of at least 0.75 on offense or at least 0.75 on defense, the larger deciding the side (offense if equal); Out and Doubtful count as out.

- Decisions:
  - 1. Who counts as a non-QB. A player is excluded from key starters if he is a QB under Amendment 11's definition as of the game's cutoff: listed as QB in the nflverse players table, or recorded as a team's starting QB (home_qb_id or away_qb_id) in a game finished strictly before the cutoff. The code uses the same function for this as the QB features (plan module 9), so there is one definition. A player who is not a QB under this definition can be a key starter even if the snap counts list him as QB. The position column of the snap counts is not used.
  - 2. Zero-filled values. Each of the two value columns (own offensive value out; opponent defensive value out) has its own boolean flag column, named after the value it describes. A flag is true when the team that value comes from has fewer than 3 finished games with snap counts before the cutoff and the value was set to 0 (Amendment 11). The build report gives the count both in team-games and in table rows, and says which is which.
  - 3. Switch. The key starters build takes an on/off setting. When off, the two value columns and their two flag columns are absent from the table (not zero). Every other column is identical with the switch on or off, and the build checks this.

---

## Amendment 16 (2026-10-17, before any model run)

- Purpose. Settles three points the assembled as-of-cutoff feature table (plan module 11) needs before it is built. Written before any assembly code exists and before any model result. The layout of Amendment 12 decision 19 stays: one row per version 1 game except 2011_13_DET_NO, team-level features twice with home_ and away_ prefixes, game-level facts once.

- Decisions:
  - 1. Columns beyond decision 19's list.
    - a. The training-exclusion flag and its reason (Amendment 11; Amendment 14 decisions 2 and 3) appear once, as game-level columns train_exclude and exclude_reason, not per side. The build checks that the home and away rows of the QB features (plan module 9) agree on both, and stops with an error if they do not.
    - b. The two key-starter zero-fill flags (Amendment 15 decision 2) are included per side, named after the value they describe with the side prefix. They are absent when the key starters switch is off, like the value columns (Amendment 15 decision 3).
    - c. Diagnostic columns (QB statuses, the primary and substitute paths, the unblended primary and substitute QB features, and the blend's g and w) are not in the table. The table holds model inputs, ids and flags only. The diagnostic columns stay in the module output files.
  - 2. Column names. Team-level columns are the side prefix (home_ or away_) plus the source module's column name, for example home_pass_epa_off, away_pace, home_qb_pass, home_primary_qb_id, home_P, home_own_off_value_out, home_opp_def_value_out, home_rest, home_tz_shift. Game-level columns are game_id, season, week, group, primetime, div_game, roof_category, neutral, train_exclude and exclude_reason. The neutral column is derived from the schedules location field (1 if Neutral, else 0), not set to a constant, and the build checks that it is 0 on every row.
  - 3. Combinations. The table is written for all 18 combinations: half-life 4, 8 or 16, ablation run full, without QB rushing or without any QB term, and key starters on or off, with file names such as feature_table_h8_full_ks.parquet and feature_table_h8_full_noks.parquet. Test 1 runs the combinations of Amendment 12 decision 22 (3 half-lives x 3 ablation runs) with key starters on; the table with key starters off has a subset of those columns, so decision 24's comparison of every column covers it.

---

## Amendment 17 (2026-10-21, before any test 1 code exists and before any test 1 result)

- Purpose. Settles how test 1 (Amendment 12 decisions 21 to 24) is carried out, from the module 12 design review of 2026-10-21. Amendment 12 decisions 21 to 24 stand; this amendment makes them exact.

- Decisions:
  - 1. Plays table. Step (a) reduces the saved clean_plays.parquet; clean_pbp is not rerun for each cutoff. This relies on cleaning depending only on each game's own plays and static tables. The test checks it: for 3 sampled cutoffs (one each in 2013, 2018 and 2024), clean_pbp run on the raw play-by-play of only the games finished strictly before C must equal the reduced clean_plays under the play comparison of decision 8. A difference fails test 1.
  - 2. Finish times in the reducer. The test computes each game's finish itself from the raw schedules gameday and gametime (America/New_York, plus 4 hours, Amendment 12 decision 1), without calling features/game_times.py. Once, on unpatched code and before the positive controls, it checks that this finish equals module 1's finish for every game from 2010 to 2024. A mismatch stops test 1. The reducer always uses its own finish times. Each tested game's cutoff C is taken from module 1.
  - 3. Injury reduction. "Stamped after C" uses the Amendment 11 reading (2010 to 2020 clock time read as Pacific, 2021 to 2024 read as UTC), implemented in the test itself, not by calling features/injury_status.py. Rows with no date_modified are removed. "Weeks after G's week" means every row whose (season, week) is later than G's (season, week); rows of earlier seasons are kept.
  - 4. One deleted build per cutoff. The reductions depend only on C and G's (season, week), and every cutoff belongs to one game-week (Amendment 13 decision 3), so one deleted build per cutoff and setting supplies the rows of every game at that cutoff. The test checks that every cutoff maps to exactly one (season, week) and stops otherwise.
  - 5. No reuse across cutoffs. Each cutoff's deleted build is made from scratch from that cutoff's reduced tables: fits, end-of-season fits, the P pool, the league-average backup pool, QB sets, key-starter windows and every input object. Nothing computed for another cutoff or for the full build is reused. Within one cutoff, inputs that do not depend on the setting may be built once and shared across the 9 settings, as the full build does.
  - 6. Code changes before test 1. In features/ (plan modules 1 to 11 and clean_pbp), changes that only let code take tables instead of reading files, or that add a games filter, are allowed. The full existing test suite is run under /usr/bin/python3 and under .venv before the change and after it, and the results must be the same apart from tests added for test 1. After the change and before test 1 runs: (a) all 18 feature tables are rebuilt fresh and must match the saved 2026-10-17 tables under the feature comparison of decision 8; (b) clean_plays is rebuilt fresh and must match the saved clean_plays.parquet under the play comparison of decision 8; (c) for the sampled cutoffs of decision 10, the full build with a games filter must equal the same rows of the unfiltered full build. Any difference stops test 1 until the change is fixed.
  - 7. Full build reference. The full build compared in test 1 is built fresh in the same run, from the same code and inputs as the deleted builds. The saved tables are used only for decision 6.
  - 8. Comparison. For all comparisons: values are compared, not types (equal values in int32 and int64, or in the two text types, are equal); missing equals only missing, and None, pd.NA and NaN all count as missing; in Amendment 12 decision 24's tolerance, a is the full build value (or the saved value in decision 6).
    - Feature tables. Rows are matched on game_id. Exact equality applies to game_id, group, roof_category, exclude_reason, the primary and substitute QB ids, season, week and rest, and to the flag columns. train_exclude and the zero-fill flags must hold booleans; primetime, div_game, neutral, short_week and bye must hold 0 or 1. Any other value in a flag column is a failure. Every other column uses the tolerance.
    - Play tables (decisions 1 and 6 (b)). Rows are matched on (game_id, play_id), and both sides must have the same set of keys. Columns with a numeric type in the saved clean_plays.parquet use the tolerance; every other column needs exact equality as text.
  - 9. Structure. Test 1 also fails if a deleted build raises an error, returns a missing or extra row for the games at C, or has a missing or extra column.
  - 10. Positive controls. Before the full run, three deliberate leaks, kept in tests/ only, run on a sample of cutoffs, along with the unpatched build on the same sample. The decision 2 check is not run inside a control. (A) A column counting the game's own plays in the plays table the build received must fail on every sampled game. (B) Module 1's finish time patched to kickoff minus 3 days inside both builds, with the reducer keeping its own finish times, must fail on every sampled mid-season game. (C) Injury status built ignoring date_modified must fail on every game sampled for it. Games for C are chosen by a read-only scan as games where ignoring date_modified changes a team's primary QB, that QB's P, or whether a key starter counts as out. If the scan finds no such game, test 1 stops and the result is reported. The unpatched build must show zero failures on the sample. If any control does not fire, or the unpatched sample fails, test 1 stops before the full run. A synthetic test also covers a game finishing exactly at C (Amendment 12 decision 2), since no real 2010 to 2024 game does.
  - 11. Full run gate. Run times are measured on the sample first and reported. The full run (587 cutoffs x 9 settings) starts only after Cam approves it from those numbers.
  - 12. Key starters off. Deleted builds are not run with key starters off. Instead, test 1 runs the identity check of Amendment 15 decision 3 on the fresh full build for all 9 settings: with the switch off, the two value columns and two flag columns are absent and every other column is identical to the switch on. A failure fails test 1.

- Known limits (not tested by test 1):
  - Schedule rows of unfinished games are kept, so these rely on their own rules and tests: the Outdoors list, the game-week index, g and the first-game check, later edits to gametime (Amendment 12 decision 1), and home_rest and away_rest.
  - Static tables: the players table is a current snapshot, including the QB listing, the pfr links and the designed_qb_run flag stored in clean_plays.
  - Frozen settings (Amendment 12 decision 20).
  - Cutoff values come from module 1. Test 1 checks leakage relative to them, not that they mirror the live cutoff rule.
  - A leak in code that runs only with key starters off, and touches no column that also exists with them on, is covered only by decision 12's check on the full build.

- Counts from the 2026-10-21 design review: 3,007 version 1 games and 587 distinct cutoffs in 2013 to 2024; 62 regular season injury rows with no date_modified, none Out, Doubtful or Questionable.

---

## Amendment 18 (2026-10-21, before any test 1 code exists and before any test 1 result)

- Purpose. Replaces control B of Amendment 17 decision 10. As written, control B fires only through an error (qb_features.py:177 stops on a missing starting QB id in the deleted build), so it never shows that test 1 catches wrong values produced by production code. Written before any test 1 code exists and before any test 1 result.

- Decisions:
  - 1. Control B. Inside both builds, module 6's rating fit at cutoff C (features/ratings.py fit) is patched to also use the plays of every game in the predicted game-week P, including G, whether or not they finished before C. Those plays have age 0, so the negative-age stop of Amendment 12 decision 5 is not reached. The end-of-season fit, module 1 and the reducer are not patched. Control B runs only on sampled games where at least one team has g of 1 or more (Amendment 10), because when both teams have g = 0 the blend weight w is 0 and the current fit cannot move a rating (189 such version 1 games in 2013 to 2024, all in week 1). On every such sampled game, control B must fail through a value difference in at least one of the 8 blended rating columns.
  - 2. Firing means a value difference. For controls A, B and C, a control fires on a game only if the comparison of Amendment 17 decision 8 finds a value difference in that game's row. A control game whose deleted build or full build raises an error does not count as firing; it is reported with the error, and test 1 stops before the full run.
  - 3. Everything else in Amendment 17 decision 10 stands, including control A, control C and its selection scan, the unpatched sample with zero failures, and the synthetic test of a game finishing exactly at C. Amendment 17 decision 9 (an error in the real test 1 run is a failure) is unchanged.

---

## Amendment 19 (2026-10-24, before any test 1 code exists and before any test 1 result)

- Purpose. Amendment 17 decision 10 does not define the sample of cutoffs, how it is drawn, which settings the controls run, how Amendment 17 decision 1's 3 cutoffs and the control C games are chosen, or what is timed. This settles them before any test 1 code or result.

- Decisions:
  - 1. Main sample (Amendment 17 decisions 6(c), 10 and 11). 14 cutoffs from the 587 version 1 cutoffs of 2013 to 2024, taken from module 1's game_times. "Week" here means the schedule week column, not the game-week index of Amendment 12 decision 5. (a) One cutoff per season 2013 to 2024 from the cutoffs whose week is 2 or later. One generator, rng = numpy.random.default_rng(20261024), is created once. For each season in ascending order, that season's eligible cutoffs are sorted ascending and the one at index int(rng.integers(len(cutoffs))) is taken. (b) For 2013 and for 2024, the week 1 cutoff with the most version 1 games; ties go to the earliest. The 14 cutoffs and their games are printed and saved with the test output before any build runs.
  - 2. Amendment 17 decision 1 cutoffs. The 2013, 2018 and 2024 cutoffs drawn in decision 1 (a).
  - 3. Control C sample. The read-only scan of Amendment 17 decision 10 runs over all 3,007 version 1 games and lists its hits sorted by game_id. If there are 10 or fewer hits, all are used. If more, a fresh generator numpy.random.default_rng(20261024) selects rng.choice(len(hits), size=10, replace=False), sorted ascending. The control C cutoffs are the cutoffs of the selected games. Control C runs only at those cutoffs and must fire on every selected game. Other games at those cutoffs are not checked for firing. If a control C cutoff is also one of the 14, it is not run twice by the unpatched build.
  - 4. What runs where. At the 14 cutoffs: the unpatched build in all 9 settings of Amendment 12 decision 22, key starters on, with zero failures on every game; control A in h8 full with key starters on, which must fire on every game; control B in h8 full with key starters on, which must fire on every game where at least one team has g of 1 or more (Amendment 18 decision 1). If no such game exists, test 1 stops and reports. At the control C cutoffs: control C in h8 full with key starters on, and the unpatched build in h8 full with key starters on, with zero failures on every game. Controls A and B do not run at the control C cutoffs.
  - 5. Amendment 17 decision 6(c). It runs at every cutoff and setting where the unpatched build runs under decision 4. The filter is the games at that cutoff.
  - 6. Timing (Amendment 17 decision 11). Recorded and reported: the Amendment 17 decision 2 finish check (once); the Amendment 17 decision 1 clean_pbp check (per cutoff); reduction (per cutoff); deleted build (per cutoff and setting); full build (once per setting, and once per control, since each control patches its own full build); the Amendment 17 decision 6(c) filtered build (per cutoff and setting); comparison (per cutoff and setting); the Amendment 17 decision 12 identity check (once); and the total.

---

## Amendment 20 (2026-10-24, before any test 1 code exists and before any test 1 result)

- Purpose. The test 1 harness design review of 2026-10-24 found that control C's patch and scan, the timing of shared inputs, and the gate for the full run are not exact enough to code. This settles them before any test 1 code or result.

- Decisions:
  - 1. Control C patch. "Injury status built ignoring date_modified" (Amendment 17 decision 10) means: inside both builds, features/injury_status.py joined is patched so that every injury row with a date_modified counts as in time at the cutoff. The latest row is still chosen by date_modified. Rows with no date_modified stay unused, as in production. If the patch triggers the tie error in injury_status.build, that is an error under Amendment 18 decision 2 and test 1 stops.
  - 2. Control C scan. The scan applies the patch of decision 1 and compares against the unpatched code at each game's own cutoff. A game is a hit if, for either team, (a) the primary QB id changes, (b) the primary QB's P changes, where P is looked up in the unpatched P table so that only the QB's own status at G can move it, or (c) any of the four key starter values (off, def, out_off, out_def) changes. This replaces "whether a key starter counts as out" in Amendment 17 decision 10. A game whose key starters swap with equal shares and no value change is not a hit.
  - 3. Control B scope. The patched ratings.fit is also used by qb_features, so control B may change QB columns too. Firing is still judged only on the 8 blended rating columns (Amendment 18 decision 1).
  - 4. Timing of shared inputs. Each build calls build_from_tables once per cutoff. Inputs shared across settings (times, context, rating data, QB inputs, key starter inputs) are timed as their own line per cutoff, and once for each full build. The per-setting figures of Amendment 19 decision 6 exclude that shared part.
  - 5. Full run gate. --sample writes data/historical/derived/test1/summary.json with: pass or fail for every check, git HEAD, and SHA-256 hashes of every file in features/ and tests/, of docs/backtest_rules_v1.md, and of every input file load_tables() and the reducer read. --full refuses to run unless --approved is given and summary.json shows a pass with every hash equal to the current files. Any change to code, rules or inputs after the sample means the sample is rerun from scratch (Amendment 12 decision 24).

---

## Amendment 21 (2026-10-24, before any test 1 run and before any test 1 result)

- Purpose. Writing the test 1 harness showed that Amendment 20 decisions 4 and 5 do not say which files are hashed, where pace's time goes, or which software the sample and full run use. This settles them before any test 1 run or result.

- Decisions:
  - 1. Code files hashed. "Every file in features/ and tests/" (Amendment 20 decision 5) means the files that git ls-files --cached --others --exclude-standard lists in those folders: tracked files plus untracked files that are not git-ignored. __pycache__ and other git-ignored files are not hashed.
  - 2. Input files hashed. Besides the files load_tables() and the reducer read, the hashes cover the raw play-by-play files read by the Amendment 17 decision 1 clean_pbp check.
  - 3. Software. summary.json also records the interpreter path and the versions of Python, pandas, numpy and pyarrow. --full refuses unless it runs under the same interpreter with the same versions.
  - 4. Pace timing. pace.build runs once per half-life and is shared by that half-life's 3 ablation runs. Its time is reported as its own line per half-life, per cutoff and per full build, and is excluded from the per-setting figures, as with the shared inputs of Amendment 20 decision 4.

---

## Amendment 22 (2026-10-26, before any tuning code exists and before any tuning result)

- Purpose. Settles the module 13 penalty tuning design from the read-only design review of 2026-10-26. Written before any tuning code exists and before any tuning result.

- Decisions:
  - 1. Tuned run. Tuning uses the full ablation run only. The run without QB rushing reuses the full run's tuned QB passing penalty, because its pass regression is the same model as the full run's (same design, passer indicators and penalties). This closes the open item in Amendment 12, the QB passing penalty in the "without QB rushing" run. The run without any QB term uses only the full run's two team penalties.
  - 2. Pass and rush team penalties. They are tuned separately and may differ. Amendment 12 decision 22's "team penalty 1000 (pass and rush)" describes test 1's values only.
  - 3. Tie rule (replaces Amendment 9's "A choice within 0.1% (relative) of the smallest error goes to the larger penalty"). For each half-life and each regression type (pass, rush), the 16 combinations are scored on the same plays. The best combination has the smallest pooled MSE. For each other combination, its per-game difference is its sum of squared errors in that game minus the best's, for each tuning game with at least one play of that regression type. The standard error is the sample standard deviation of those per-game differences (divided by the number of games minus 1), times the square root of the number of those games, divided by the total number of plays. A combination ties with the best if its pooled MSE minus the best's pooled MSE is at most one such standard error. Among the best and its ties, the winner has the largest sum of grid positions (0 to 3 for each penalty). Any remaining tie goes to the larger team penalty. MSE values are compared unrounded.
  - 4. Edge. A winner is at the edge if either penalty is at its grid minimum or maximum. It is reported and the grid is not extended (Amendment 9).
  - 5. Success-rate regressions. They reuse the EPA penalties (Amendment 9) and are not tuned. Their error is not computed or reported.
  - 6. Held-out plays. Every kept play in clean_plays.parquet of each version 1 game in nflverse seasons 2014 to 2017, including games carrying the Amendment 11 score-model training exclusion. Pass plays score the pass regression and rush plays score the rush regression.
  - 7. Prediction of a held-out play's EPA. The fit's intercept, plus its home coefficient times the play's home value (+1, -1, 0 neutral), plus the blended offense rating of the offense team, plus the blended defense rating of the defense team, plus a QB term. Pass QB term: the passer_id's indicator from the fit at the cutoff, 0 if none. Rush QB term: on designed QB runs only, the shared QB-run term plus the rusher_player_id's indicator, 0 if none. The ids and flags are the same columns the fit uses. Only the 8 team ratings are blended (Amendment 10, c = 0.5, F = 8, g as in team_ratings.games_before, prior 0 if missing). The intercept, the home coefficient, the shared QB-run term and the QB indicators come unblended from the fit at the cutoff. This is how Amendment 10's replacement of "no early-season fade" in Amendment 9 is read.
  - 8. Prior. For each half-life and penalty combination, the end-of-season fit for S-1 is recomputed with that combination, full run (Amendment 10; Amendment 13 decision 2). No prior is reused across combinations.
  - 9. Error. Unweighted MSE over all held-out plays pooled across 2014 to 2017, equal weight per play, no recency weights.
  - 10. Pairing. Pass combination i and rush combination i may share one ratings.fit call, since the two designs share no columns.
  - 11. Code. Tuning code lives in a new file outside features/, and features/ is not changed. The blend is repeated there, and a test shows that its blended ratings are identical floats to team_ratings.build output at the test 1 values for a sample of cutoffs.
  - 12. Failure. If any solve fails the Cholesky or non-finite check, the run stops and reports. No combination is skipped.
  - 13. Run gate. A timing run of single fits comes first, then a sample run, then a full run only after Cam approves it from the measured times. Long runs use python -u with progress lines, run from Terminal with nohup and caffeinate.
  - 14. Recording. The run writes the full grid (half-life, regression type, combination, MSE, play and game counts, standard error, tie flag, winner, edge flag) plus git HEAD, hashes and software to a git-ignored data/historical/derived/tuning/. It is copied unchanged to docs/tuning_results/. The tuned values are recorded in a later dated amendment before any code uses them.

---

## Amendment 23 (2026-10-26, after the penalty tuning run, recording its result)

- Purpose. Records the tuned penalties from the full module 13 run (Amendment 22). The evidence is in docs/tuning_results/ (grid.csv, per_game.csv, timing.csv, summary.json and README.md), from tuning/penalties.py at commit 9040fdf.

- Decisions:
  - 1. Tuned penalties per half-life, as Penalties(pass_team, pass_qb, rush_team, rush_qb): h4 (100, 3000, 300, 1600); h8 (300, 300, 1000, 1600); h16 (300, 300, 1000, 1600). They replace test 1's fixed values from test 2 on (Amendment 9). The success-rate regressions reuse them. The run without QB rushing uses the same pass penalties and the rush team penalty. The run without any QB term uses only the two team penalties (Amendment 22 decision 1).
  - 2. Edge winners, reported and not extended (Amendment 9): every rush winner is at the top of the QB rushing grid (1600), and the h4 pass winner is at the edge of both grids (team 100, QB 3000).
  - 3. Known limit, recorded and not changed, because the rule was fixed before any result. At h4 pass, the best combination was 300 / 300 (pooled MSE 2.49452), and Amendment 22 decision 3's grid-position sum chose 100 / 3000 (pooled MSE 2.49491), a smaller team penalty traded for a larger QB penalty. Its pooled MSE is 0.000384879 above the best's, within one standard error (0.00046723, grid.csv). Combinations far from the best have larger standard errors, so they tie more easily. Any future tuning rule should require the winner to be at least as large as the best in both penalties.

---

## Amendment 24 (2026-10-26, before any carry factor code exists and before any carry factor result)

- Purpose. Settles the module 14 carry factor design from the read-only design review of 2026-10-26. Written before any carry factor code exists and before any carry factor result.

- Decisions:
  - 1. Fits. For each of the 9 settings (half-lives 4, 8, 16 x the full run, the run without QB rushing, the run without any QB term), one end-of-season fit per season 2010 to 2017 (Amendment 10; Amendment 13 decision 2), 72 in all. Each setting uses its half-life's Amendment 23 penalties, the same Penalties for all three runs, and the fit ignores fields a run does not use (Amendment 22 decision 1). The code stops if any fitted play finishes after the finish of the last 2017 regular season game.
  - 2. Pairs. For S = 2010 to 2016: x is the team's season S indicator from the end-of-season fit for S, and y is its season S+1 indicator from the end-of-season fit for S+1. Teams are matched by today's codes (Amendment 5; Amendment 12 fact f and decision 15), so a franchise that moved is paired across the move. The code stops unless every rating type in every setting has exactly 224 pairs with no missing value.
  - 3. Form. c = sum(x times y) / sum(x squared) over the 224 pairs: unweighted, through the origin, no centering. The standard error of c is sqrt( sum((y - c x)^2) / (n - 1) / sum(x^2) ), with n = 224 and the raw c. The pair count, the standard error of c and the per-season means of x and y are reported for information only, and nothing depends on them.
  - 4. Bounds. The raw c is recorded. The value used in the blend is the raw c clipped to between 0 and 1, and each clipped value is flagged. This bound is fixed before any carry factor is computed.
  - 5. Rating types. c is estimated for all 8 rating types, the success-rate types included, from the same fits, which use the EPA penalties (Amendment 9; Amendment 10).
  - 6. Code. tuning/carry_factor.py; features/ is not changed. A constant holds the Amendment 23 penalties, and a test checks it against the winners in docs/tuning_results/grid.csv. Tests also cover the formula and the clipping on a hand-built example, and the 224-pair check. The module 14 row of docs/feature_table_plan.md is updated to the new path in the code commit.
  - 7. Run gate. The run is estimated at about 3 seconds of fitting (72 end-of-season fits at 0.0382 s each, measured in docs/tuning_results/timing.csv). Amendment 22 decision 13's sample step covers module 13 only; module 14 has no sample stage. One run, after the tests pass, which refuses unless given --approved with features/, tuning/ and tests/ clean in git. Any failed solve stops the run (as in Amendment 22 decision 12).
  - 8. Recording. The run writes to a git-ignored data/historical/derived/carry_factor/: c.csv (72 rows: half-life, run, rating type, raw c, c used, clipped flag, pairs, standard error, per-season means of x and y), pairs.csv (every setting, type, team, S, x and y), and summary.json (git HEAD, software, hashes). They are copied unchanged to docs/carry_factor_results/ with a README. The values are recorded in a later dated amendment before any code uses them.
  - 9. Known limit. The rating model has one intercept across all seasons, so a league-wide change in EPA from one season to the next sits in every team's season indicators. c therefore mixes team carry-over with league drift. The blend applies c to the same uncentered prior, so this is consistent, and the per-season means in decision 3 show its size.
