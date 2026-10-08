# Reads data/historical/pbp/play_by_play_2010..2024.parquet (fixed path); scramble coding, dropback definitions (a)/(b)/(c), passer id coverage, (a) vs (b) differences; numbers behind Amendment 7 (dropback and scramble rules).
import pandas as pd
pd.set_option('display.width', 250); pd.set_option('display.max_rows', 500); pd.set_option('display.max_colwidth', 120)
R = '/Users/cameronwood/nfl-model/data/historical/pbp'
cols = ['game_id','season','season_type','qtr','time','desc','play_type','pass','rush','pass_attempt','rush_attempt','sack',
        'qb_dropback','qb_scramble','qb_kneel','qb_spike','epa','wp','passer_player_id','passer_id','rusher_player_id','rusher_id']
d = pd.concat([pd.read_parquet(f'{R}/play_by_play_{y}.parquet', columns=cols) for y in range(2010, 2025)], ignore_index=True)
n0 = len(d)
d = d.drop_duplicates(['game_id','qtr','time','desc'], keep='first')
d = d[d.game_id != '2011_13_DET_NO']
print('rows', n0, '-> after dedup + DET_NO', len(d))
flags = ['pass','rush','pass_attempt','rush_attempt','sack','qb_dropback','qb_scramble','qb_kneel','qb_spike']
for c in flags: print(c, 'nulls by season:', d.groupby('season')[c].apply(lambda s: s.isna().sum()).to_dict() if d[c].isna().any() else 0)
rel = d[(d[flags].fillna(0).sum(axis=1) > 0) | d.play_type.isin(['pass','run','qb_kneel','qb_spike'])].copy()
for c in flags: rel[c] = rel[c].fillna(-1).astype(int)
rel['play_type'] = rel.play_type.fillna('NA')
key = ['play_type'] + flags
print('\n== 1. combinations (all seasons) ==')
combo = rel.groupby(key).size().rename('n').reset_index().sort_values('n', ascending=False)
print(combo.to_string(index=False))
print('\n== 1/2. per-season counts of main combos ==')
rel['combo'] = rel[key].astype(str).agg('|'.join, axis=1)
top = combo.head(12)[key].astype(str).agg('|'.join, axis=1)
print('combo key order:', key)
print(rel[rel.combo.isin(top)].pivot_table(index='combo', columns='season', values='qtr', aggfunc='size', fill_value=0).to_string())
print('\nscrambles (qb_scramble==1) by season:', rel[rel.qb_scramble==1].groupby('season').size().to_dict())
print('scramble play_type mix:', rel[rel.qb_scramble==1].groupby('play_type').size().to_dict())

# A5 universe
U = d[((d['pass']==1)|(d.rush==1)) & (d.qb_kneel!=1) & (d.qb_spike!=1) & d.epa.notna()].copy()
G = U[(U.wp>=0.05)&(U.wp<=0.95)]
def defs(x):
    a = (x.pass_attempt==1)|(x.sack==1)
    b = x.qb_dropback==1
    scr = x.qb_scramble==1
    c = b | scr
    return a, b, c, scr
print('\n== 3. definitions on A5 plays (pass|rush, no kneel/spike, epa present) ==')
for lab, X in [('BEFORE garbage-time removal', U), ('AFTER garbage-time removal (wp 0.05-0.95)', G)]:
    a,b,c,scr = defs(X); pp = X['pass']==1
    rows=[]
    for s, g in X.groupby('season'):
        i = g.index
        r={'season':s,'pass_plays':pp[i].sum()}
        for nm,m in [('a',a),('b',b),('c',c)]:
            r[f'{nm}_n']=m[i].sum(); r[f'{nm}_epa']=round(X.loc[i][m[i]].epa.mean(),4)
            r[f'{nm}_nopasser%']=round(100*(pp[i]&~m[i]).sum()/pp[i].sum(),2)
        r['scr_in_b']=(scr[i]&b[i]).sum(); r['scr_not_b']=(scr[i]&~b[i]).sum(); r['scr_epa']=round(X.loc[i][scr[i]].epa.mean(),4)
        rows.append(r)
    t=pd.DataFrame(rows); print('\n--',lab,'--'); print(t.to_string(index=False))
    tot={k:(t[k].sum() if k.endswith('_n') or k in('pass_plays','scr_in_b','scr_not_b') else None) for k in t.columns}
    print('pooled:', {nm:(int(m.sum()), round(X[m].epa.mean(),4), round(100*(pp&~m).sum()/pp.sum(),2)) for nm,m in [('a',a),('b',b),('c',c)]})
    print('pass plays not in (b), by combo:'); print(X[pp & ~b].assign(pt=X.play_type).groupby(['pt','pass_attempt','sack','qb_scramble','rush']).size().to_string())
    print('in (b) but not pass==1:', (b & ~pp).sum())

print('\n== 4. passer id missing (% of qualifying plays), after garbage-time removal ==')
a,b,c,scr = defs(G)
rows=[]
for s,g in G.groupby('season'):
    i=g.index; r={'season':s}
    for nm,m in [('a',a),('b',b),('c',c)]:
        q=G.loc[i][m[i]]
        r[f'{nm}_passer_player_id%']=round(100*q.passer_player_id.isna().mean(),2)
        r[f'{nm}_passer_id%']=round(100*q.passer_id.isna().mean(),2)
    q=G.loc[i][scr[i]]
    r['scr_passer_player_id%']=round(100*q.passer_player_id.isna().mean(),2); r['scr_passer_id%']=round(100*q.passer_id.isna().mean(),2)
    r['scr_rusher_id%']=round(100*q.rusher_id.isna().mean(),2)
    r['scr_passer_id==rusher_id%']=round(100*(q.passer_id==q.rusher_id).mean(),2)
    rows.append(r)
print(pd.DataFrame(rows).to_string(index=False))
q=G[b]; print('(b) passer_id vs passer_player_id disagree when both present:', ((q.passer_id!=q.passer_player_id)&q.passer_id.notna()&q.passer_player_id.notna()).sum())
print('(b) sacks: passer_player_id missing', round(100*G[b&(G.sack==1)].passer_player_id.isna().mean(),2), '% ; passer_id missing', round(100*G[b&(G.sack==1)].passer_id.isna().mean(),2),'%')

print('\n== 5. (a) xor (b), all cleaned rows ==')
A=(rel.pass_attempt==1)|(rel.sack==1); B=rel.qb_dropback==1
x=rel[A!=B].assign(side=lambda z: (A[z.index]).map({True:'a_only',False:'b_only'}))
grp=x.groupby(['side']+key).size().rename('n').reset_index().sort_values('n')
print(grp.to_string(index=False))
for _,r in grp.iterrows():
    m=(x.side==r.side)
    for k in key: m &= x[k]==r[k]
    print('\n', r.side, dict(r[key]), 'n=',r.n, 'seasons', x[m].season.value_counts().sort_index().to_dict())
    for _,e in x[m].head(3).iterrows(): print('   ', e.game_id, '|', str(e.desc)[:160])
