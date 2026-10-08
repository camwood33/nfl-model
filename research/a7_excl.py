# Reads data/historical/pbp/play_by_play_2010..2024.parquet (fixed path), writes a7_table.md to data/historical/derived/ (fixed path); produces Amendment 7's exclusion table by reason and season.
import pandas as pd, numpy as np
R = '/Users/cameronwood/nfl-model/data/historical/pbp'
cols = ['game_id','season','qtr','time','desc','play_type','pass','rush','qb_dropback','qb_kneel','qb_spike','two_point_attempt','epa','wp','passer_id']
d = pd.concat([pd.read_parquet(f'{R}/play_by_play_{y}.parquet', columns=cols) for y in range(2010, 2025)], ignore_index=True)
d = d.drop_duplicates(['game_id','qtr','time','desc']); d = d[d.game_id != '2011_13_DET_NO']
pt = d.play_type
base = (d['pass']==1)|(d.rush==1)|pt.isin(['pass','run','qb_kneel','qb_spike'])
d = d[base].copy(); pt = d.play_type
db = d.qb_dropback==1
rules = [
 ('no_play', pt=='no_play'),
 ('kneel', (pt=='qb_kneel')|(d.qb_kneel==1)),
 ('spike', (pt=='qb_spike')|(d.qb_spike==1)),
 ('other play_type', ~pt.isin(['pass','run'])),
 ('pass=0 and rush=0', (d['pass']!=1)&(d.rush!=1)),
 ('two-point attempt', d.two_point_attempt==1),
 ('null epa', d.epa.isna()),
 ('garbage time', (d.wp<0.05)|(d.wp>0.95)),
 ('fits neither regression', ~db & ~((d.rush==1)&~db)),
 ('dropback, blank passer_id', db & d.passer_id.isna()),
]
reason = pd.Series('kept', index=d.index)
for name, m in reversed(rules): reason[m] = name
d['reason'] = np.where(reason=='kept', np.where(db,'kept: pass regression','kept: rush regression'), reason)
order = [r for r,_ in rules] + ['kept: pass regression','kept: rush regression']
t = d.pivot_table(index='season', columns='reason', values='qtr', aggfunc='size', fill_value=0).reindex(columns=order, fill_value=0)
t.loc['Total'] = t.sum()
t.insert(0, 'Candidate plays', t.sum(axis=1))
print(t.to_string())
print('\nother play_type breakdown:', d[d.reason=='other play_type'].play_type.fillna('NA').value_counts().to_dict())
print('fits neither, by play_type:', d[d.reason=='fits neither regression'].play_type.value_counts().to_dict())
md = '| Season | ' + ' | '.join(t.columns) + ' |\n|' + '---|'*(len(t.columns)+1) + '\n'
for s, r in t.iterrows(): md += f'| {s} | ' + ' | '.join(f'{int(v):,}' for v in r) + ' |\n'
open('/Users/cameronwood/nfl-model/data/historical/derived/a7_table.md','w').write(md)
