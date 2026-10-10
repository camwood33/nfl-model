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
