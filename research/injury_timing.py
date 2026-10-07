import sys, glob
import pandas as pd
ROOT = '/Users/cameronwood/nfl-model/data/historical'
ET = 'America/New_York'
DAYS_BEFORE = int(sys.argv[1]) if len(sys.argv) > 1 else 2   # 2 = main cutoff, 1 = fallback

g = pd.read_parquet(f'{ROOT}/schedules/games.parquet')
g = g[g.season.between(2010, 2024) & (g.game_type == 'REG')].copy()
g['gd'] = pd.to_datetime(g.gameday)
g['wd'] = g.gd.dt.day_name()
long = pd.concat([
    g[['season', 'week', 'home_team', 'wd', 'location', 'gd']].rename(columns={'home_team': 'team'}),
    g[['season', 'week', 'away_team', 'wd', 'location', 'gd']].rename(columns={'away_team': 'team'})])

d = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(f'{ROOT}/injuries/injuries_*.parquet'))
               if 2010 <= int(f[-12:-8]) <= 2024], ignore_index=True)
d = d[(d.game_type == 'REG') & d.report_status.isin(['Out', 'Doubtful', 'Questionable'])]
m = d.merge(long, on=['season', 'week', 'team'], how='left', indicator=True)
print('rows with no schedule match:', (m._merge != 'both').sum(),
      m.loc[m._merge != 'both', ['season', 'week', 'team']].drop_duplicates().values.tolist())
m = m[m._merge == 'both'].copy()

# Cutoff: 8pm ET, DAYS_BEFORE calendar days before game date; Thursday always Wednesday 8pm
days = m.wd.map(lambda w: 1 if w == 'Thursday' else DAYS_BEFORE)
m['cutoff'] = (m.gd - pd.to_timedelta(days, unit='D') + pd.Timedelta(hours=20)).dt.tz_localize(ET)

naive = m.date_modified.dt.tz_localize(None)
old = m.season <= 2020
utc_et = m.date_modified.dt.tz_convert(ET)
best = utc_et.copy(); worst = utc_et.copy()
best[old] = naive[old].dt.tz_localize(ET).dt.tz_convert(ET)
worst[old] = naive[old].dt.tz_localize('America/Los_Angeles').dt.tz_convert(ET)
m['ok_best'] = (best <= m.cutoff).fillna(False).astype(bool)
m['ok_worst'] = (worst <= m.cutoff).fillna(False).astype(bool)
m['ok_exact'] = m.ok_best  # identical for 2021+ (true UTC)
m['qb'] = m.position == 'QB'
m['nostamp'] = m.date_modified.isna()

print(f'cutoff: {DAYS_BEFORE} days before (Thursday: Wednesday)')
for grp in ['Thursday', 'Sunday', 'Monday']:
    gm = g[(g.wd == grp) & (g.location != 'Neutral')]
    x = m[(m.wd == grp) & (m.location != 'Neutral')]
    print(f'\n{grp}: games {len(gm)}')
    for crit, y in [('all', x), ('QB', x[x.qb])]:
        r = y[y.season >= 2021]
        print(f'  {crit:3} rows {len(y):6}  no-stamp {y.nostamp.sum():3}  best {y.ok_best.mean():.4f}  '
              f'worst {y.ok_worst.mean():.4f}  | 2021-24 rows {len(r):5} exact {r.ok_exact.mean():.4f}')
ex = g[g.wd.isin(['Tuesday', 'Wednesday']) & (g.location != 'Neutral') | g.wd.isin(['Tuesday', 'Wednesday'])]
print('\nTue/Wed games 2010-2024:', ex[['game_id', 'gameday', 'wd']].values.tolist())
print('Neutral games 2010-2024:', (g.location == 'Neutral').sum(), ' other weekday (Fri/Sat) non-neutral:',
      g[g.wd.isin(['Friday', 'Saturday']) & (g.location != 'Neutral')].wd.value_counts().to_dict())
