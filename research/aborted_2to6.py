# Reads qb_runs.parquet and players.parquet in data/historical/derived/ (run fetch_players.py first) plus data/historical/pbp/play_by_play_2010..2024.parquet (fixed paths); aborted-play rule, EPA, top-10 shares, per-QB-season counts, handoffs; numbers behind Amendment 8 (aborted plays, evidence, scale facts).
import re, pandas as pd, numpy as np
pd.set_option('display.width', 250); pd.set_option('display.max_colwidth', 200); pd.set_option('display.max_rows', 200)
S = '/Users/cameronwood/nfl-model/data/historical/derived'
R = '/Users/cameronwood/nfl-model/data/historical/pbp'
q = pd.read_parquet(f'{S}/qb_runs.parquet')
a = q[q.ab]
# ---- item 2
print('== 2. rules ==')
flag = q.aborted_play==1
print('aborted_play==1:', flag.sum(), '| text "Aborted":', q.ab.sum(), '| both:', (flag&q.ab).sum(), '| differ:', (flag!=q.ab).sum())
ho = q.desc.str.contains(r'hand ?off|handoff|exchange', case=False)
print('rule A (aborted_play==1) would remove', flag.sum(), 'of which handoff-text', (flag&ho).sum())
rest = q[~flag]
snapkw = r'snap|aborted|exchange|muff'
fum = rest[rest.fumble==1]
print('\nnon-aborted designed QB runs with fumble==1:', len(fum), '| lost:', int(fum.fumble_lost.sum()))
sus = fum[fum.desc.str.contains(snapkw, case=False)]
print('  of those, desc mentions snap/aborted/exchange/muff (possible missed aborted snaps):', len(sus))
for _,e in sus.head(10).iterrows(): print('   ', e.game_id, '|', e.desc[:200])
print('  5 examples of non-aborted fumbled QB runs (class b):')
for _,e in fum.sample(5, random_state=2).iterrows(): print('   ', e.game_id, '|', e.desc[:200])
# rushing yards / first part pattern for fumbled runs: QB runs then fumbles
fum_after = fum.desc.str.contains(r'for -?\d+ yards?.*FUMBLES|for no gain.*FUMBLES', regex=True)
print('  fumbled runs where FUMBLES follows a run with yardage:', fum_after.sum(), 'of', len(fum))
# no-fumble non-aborted with snap words
other = rest[(rest.fumble!=1) & rest.desc.str.contains(r'snap', case=False)]
print('non-aborted, no fumble, desc mentions "snap":', len(other))
for _,e in other.head(6).iterrows(): print('   ', e.game_id, '|', e.desc[:200])
# ---- item 3
print('\n== 3. mean EPA ==')
q['grp'] = pd.cut(q.season, [2009,2014,2019,2024], labels=['2010-14','2015-19','2020-24'])
t = q.groupby('grp', observed=True).apply(lambda g: pd.Series({'n_all':len(g),'epa_all':g.epa.mean(),'n_aborted':g.ab.sum(),'epa_aborted':g[g.ab].epa.mean(),'n_rest':(~g.ab).sum(),'epa_rest':g[~g.ab].epa.mean()}))
t.loc['All']=[len(q),q.epa.mean(),q.ab.sum(),q[q.ab].epa.mean(),(~q.ab).sum(),q[~q.ab].epa.mean()]
print(t.round(3).to_string())
print('handoff-text aborted EPA mean:', round(q[q.ab&ho].epa.mean(),3), 'n', (q.ab&ho).sum())
# ---- item 4
print('\n== 4. top-10 ==')
top = q.groupby(['rusher_player_id','name']).agg(runs=('epa','size'), aborted=('ab','sum')).sort_values('runs', ascending=False).head(10)
top['aborted_%'] = (100*top.aborted/top.runs).round(1); top['non_aborted']=top.runs-top.aborted
print(top.to_string())
# ---- item 5
print('\n== 5. per QB-season ==')
cols = ['game_id','season','qtr','time','desc','play_type','pass','rush','qb_dropback','qb_kneel','qb_spike','two_point_attempt','epa','wp','passer_id']
d = pd.concat([pd.read_parquet(f'{R}/play_by_play_{y}.parquet', columns=cols) for y in range(2010, 2025)], ignore_index=True)
d = d.drop_duplicates(['game_id','qtr','time','desc']); d = d[d.game_id != '2011_13_DET_NO']
E = d[d.play_type.isin(['pass','run']) & ((d['pass']==1)|(d.rush==1)) & (d.qb_kneel!=1) & (d.qb_spike!=1)
      & (d.two_point_attempt!=1) & d.epa.notna() & (d.wp>=0.05) & (d.wp<=0.95) & (d.qb_dropback==1) & d.passer_id.notna()]
dbk = E.groupby(['season','passer_id']).size().rename('dropbacks')
runs_all = q.groupby(['season','rusher_player_id']).size().rename('runs_all')
runs_na = q[~q.ab].groupby(['season','rusher_player_id']).size().rename('runs_nonab')
qs = pd.concat([dbk, runs_all.rename_axis(['season','passer_id']), runs_na.rename_axis(['season','passer_id'])], axis=1).fillna(0)
def summ(x, col):
    return {'QB-seasons':len(x),'median':float(x[col].median()),'p90':float(x[col].quantile(.9)),'share>=20 %':round(100*(x[col]>=20).mean(),1),'share>=50 %':round(100*(x[col]>=50).mean(),1)}
for lab, base in [('QB-seasons with >=1 designed run', qs[qs.runs_all>=1]), ('QB-seasons with >=200 dropbacks (A5 low-sample line)', qs[qs.dropbacks>=200]), ('QB-seasons with >=1 dropback', qs[qs.dropbacks>=1])]:
    print(lab); print('   all designed runs:', summ(base,'runs_all')); print('   excluding aborted:', summ(base,'runs_nonab'))
# ---- item 6
print('\n== 6. botched handoffs / non-QB credited, among 1,117 ==')
a = q[q.ab].copy()
a['handoff'] = a.desc.str.contains(r'hand ?off|handoff', case=False)
def first_named(t):
    m = re.search(r'\d+-([A-Z][A-Za-z\'\.\- ]*?)\s+(FUMBLES|Aborted)', t); return m.group(1) if m else None
a['center_form'] = a.desc.str.contains(r'Aborted\.\s+\d+-', regex=True)
p = pd.read_parquet(f'{S}/dl_players/players.parquet')[['gsis_id','position','display_name']].drop_duplicates('gsis_id').set_index('gsis_id')
a['fumbler_pos'] = a.fumbled_1_player_id.map(p.position)
print('by season:'); print(a.groupby('season').agg(aborted=('ab','size'), handoff_text=('handoff','sum'), center_charged_form=('center_form','sum')).to_string())
print('totals: handoff text', a.handoff.sum(), '| "QB Aborted. <player> FUMBLES" form', a.center_form.sum())
print('credited rusher position: all QB by construction (', (a.pos=='QB').mean(), ')')
print('fumbled_1_player position among aborted:', a.fumbler_pos.fillna('blank').value_counts().to_dict())
print('handoff-text examples:')
for _,e in a[a.handoff].iterrows(): print('   ', e.season, e.game_id, '|', e.desc[:220])
