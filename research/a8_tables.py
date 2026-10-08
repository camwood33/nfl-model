# Reads data/historical/pbp/play_by_play_2010..2024.parquet (fixed path), writes a8_t1.md, a8_t2.md, a8_t3.md to the session scratchpad (fixed path); produces Amendment 8's evidence tables and recomputed exclusion table.
import pandas as pd, numpy as np
S = '/private/tmp/claude-501/-Users-cameronwood-nfl-model/7dcc42ab-51ff-405f-98cb-05b49fde8564/scratchpad'
R = '/Users/cameronwood/nfl-model/data/historical/pbp'
cols = ['game_id','season','qtr','time','desc','play_type','pass','rush','qb_dropback','qb_kneel','qb_spike','two_point_attempt','aborted_play','epa','wp','passer_id']
d = pd.concat([pd.read_parquet(f'{R}/play_by_play_{y}.parquet', columns=cols) for y in range(2010, 2025)], ignore_index=True)
d = d.drop_duplicates(['game_id','qtr','time','desc']); d = d[d.game_id != '2011_13_DET_NO']
def md(t, idx):
    s = f'| {idx} | ' + ' | '.join(map(str, t.columns)) + ' |\n|' + '---|'*(len(t.columns)+1) + '\n'
    for i, r in t.iterrows(): s += f'| {i} | ' + ' | '.join(f'{int(v):,}' for v in r) + ' |\n'
    return s
# Step 1 tables
a = d[d.aborted_play==1].copy(); pt = a.play_type.fillna('NA')
ins = pt.isin(['pass','run']) & ((a['pass']==1)|(a.rush==1)) & (a.qb_kneel!=1) & (a.qb_spike!=1) & (a.two_point_attempt!=1) & a.epa.notna() & (a.wp>=0.05) & (a.wp<=0.95)
db = a.qb_dropback==1
reg = pd.Series('Not in Amendment 7 play set', index=a.index)
reg[ins & db & a.passer_id.notna()] = 'Pass regression'
reg[ins & db & a.passer_id.isna()] = 'Dropback, blank passer_id'
reg[ins & ~db & (a.rush==1)] = 'Rush regression'
reg[ins & ~db & (a.rush!=1)] = 'Fits neither'
order = [c for c in ['Pass regression','Rush regression','Fits neither','Dropback, blank passer_id','Not in Amendment 7 play set'] if (reg==c).any()]
t1 = pd.crosstab(pt, reg).reindex(columns=order, fill_value=0); t1['Total']=t1.sum(axis=1); t1.loc['Total']=t1.sum()
t2 = pd.crosstab(a.season, reg).reindex(columns=order, fill_value=0); t2['Total']=t2.sum(axis=1); t2.loc['Total']=t2.sum()
# exclusion table
pt = d.play_type
d = d[(d['pass']==1)|(d.rush==1)|pt.isin(['pass','run','qb_kneel','qb_spike'])].copy(); pt = d.play_type; db = d.qb_dropback==1
rules = [('no_play', pt=='no_play'), ('kneel', (pt=='qb_kneel')|(d.qb_kneel==1)), ('spike', (pt=='qb_spike')|(d.qb_spike==1)),
 ('other play_type', ~pt.isin(['pass','run'])), ('pass=0 and rush=0', (d['pass']!=1)&(d.rush!=1)), ('two-point attempt', d.two_point_attempt==1),
 ('aborted play', d.aborted_play==1), ('null epa', d.epa.isna()), ('garbage time', (d.wp<0.05)|(d.wp>0.95)),
 ('fits neither regression', ~db & ~((d.rush==1)&~db)), ('dropback, blank passer_id', db & d.passer_id.isna())]
reason = pd.Series('kept', index=d.index)
for n, m in reversed(rules): reason[m] = n
reason = pd.Series(np.where(reason=='kept', np.where(db,'kept: pass regression','kept: rush regression'), reason), index=d.index)
cols3 = [r for r,_ in rules] + ['kept: pass regression','kept: rush regression']
t3 = pd.crosstab(d.season, reason).reindex(columns=cols3, fill_value=0); t3.loc['Total']=t3.sum(); t3.insert(0,'Candidate plays',t3.sum(axis=1))
print(t1); print(t2); print(t3.loc['Total'])
open(f'{S}/a8_t1.md','w').write(md(t1,'play_type')); open(f'{S}/a8_t2.md','w').write(md(t2,'Season')); open(f'{S}/a8_t3.md','w').write(md(t3,'Season'))
