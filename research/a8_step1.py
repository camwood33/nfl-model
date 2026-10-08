# Reads data/historical/pbp/play_by_play_2010..2024.parquet plus players.parquet and qb_runs.parquet in the session scratchpad (fixed paths); counts aborted_play = 1 by season, play_type and regression; produces Amendment 8's Step 1 numbers.
import pandas as pd
pd.set_option('display.width', 250)
S = '/private/tmp/claude-501/-Users-cameronwood-nfl-model/7dcc42ab-51ff-405f-98cb-05b49fde8564/scratchpad'
R = '/Users/cameronwood/nfl-model/data/historical/pbp'
cols = ['game_id','play_id','season','qtr','time','desc','play_type','pass','rush','qb_dropback','qb_kneel','qb_spike','two_point_attempt','epa','wp','passer_id','rusher_player_id','aborted_play','fumbled_1_player_id']
d = pd.concat([pd.read_parquet(f'{R}/play_by_play_{y}.parquet', columns=cols) for y in range(2010, 2025)], ignore_index=True)
d = d.drop_duplicates(['game_id','qtr','time','desc']); d = d[d.game_id != '2011_13_DET_NO']
a = d[d.aborted_play==1].copy()
print('aborted_play==1 total:', len(a), '| aborted_play null rows in data:', d.aborted_play.isna().sum())
pt = a.play_type.fillna('NA')
inset = (pt.isin(['pass','run']) & ((a['pass']==1)|(a.rush==1)) & (a.qb_kneel!=1) & (a.qb_spike!=1) & (a.two_point_attempt!=1)
         & a.epa.notna() & (a.wp>=0.05) & (a.wp<=0.95))
db = a.qb_dropback==1
reg = pd.Series('not in A7 play set', index=a.index)
reg[inset & db & a.passer_id.notna()] = 'pass regression'
reg[inset & db & a.passer_id.isna()] = 'excluded: dropback, blank passer_id'
reg[inset & ~db & (a.rush==1)] = 'rush regression'
reg[inset & ~db & (a.rush!=1)] = 'excluded: fits neither'
a['reg'] = reg
p = pd.read_parquet(f'{S}/dl_players/players.parquet')[['gsis_id','position']].drop_duplicates('gsis_id').set_index('gsis_id').position
a['rpos'] = a.rusher_player_id.map(p)
a['dqr'] = (a.reg=='rush regression') & (a.rpos=='QB')
print('\nby regression:', a.reg.value_counts().to_dict())
print('by play_type:', pt.value_counts().to_dict())
print('\nplay_type x regression:'); print(pd.crosstab(pt, a.reg, margins=True).to_string())
print('\nby season:'); print(pd.crosstab(a.season, a.reg, margins=True).to_string())
print('\nin the 8,605 designed QB runs:', a.dqr.sum(), '| outside:', (~a.dqr).sum())
print('rush regression, non-QB rusher:', ((a.reg=='rush regression')&~a.dqr).sum(), a[(a.reg=='rush regression')&~a.dqr].rpos.fillna('blank').value_counts().to_dict())
q = pd.read_parquet(f'{S}/qb_runs.parquet')
fp = q[q.ab].fumbled_1_player_id.map(p)
print('\nfumbled_1 position among the 1,117:', fp.fillna('blank').value_counts().to_dict(), '| non-QB total', (fp!='QB').sum())
cf = q[q.ab].desc.str.contains(r'Aborted\.\s+\d+-', regex=True)
print('"QB Aborted. X FUMBLES" form', cf.sum(), '| of those fumbler non-QB', ((fp!='QB')&cf).sum(), '| non-QB fumbler outside that form', ((fp!='QB')&~cf).sum())
for _,e in a[a.reg=='pass regression'].sample(3, random_state=1).iterrows(): print('  pass ex:', e.game_id, '|', e.desc[:170])
