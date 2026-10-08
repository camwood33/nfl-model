# Reads data/historical/pbp/play_by_play_2010..2024.parquet (fixed path) and the nflverse players.parquet given as argv[1]; checks passer_id vs scrambler on 60 sampled scrambles; produces the Step 1 result in Amendment 7 (QB identity).
import sys, re, pandas as pd
PAT = r'^00-\d{7}$'
pd.set_option('display.width', 250); pd.set_option('display.max_colwidth', 90)
P = sys.argv[1]
R = '/Users/cameronwood/nfl-model/data/historical/pbp'
p = pd.read_parquet(P)
print('players rows', len(p)); print('id/name cols:', [c for c in p.columns if 'id' in c or 'name' in c])
idcol = 'gsis_id'
names = p.set_index(idcol)['display_name'] if 'display_name' in p.columns else None
cols = ['game_id','season','qtr','time','desc','play_type','qb_scramble','passer_id','passer','passer_player_id','rusher_id','rusher','rusher_player_id','rusher_player_name','fantasy_player_id','id','name']
allc = pd.read_parquet(f'{R}/play_by_play_2010.parquet').columns
cols = [c for c in cols if c in allc]
d = pd.concat([pd.read_parquet(f'{R}/play_by_play_{y}.parquet', columns=cols) for y in range(2010, 2025)], ignore_index=True)
d = d.drop_duplicates(['game_id','qtr','time','desc']); d = d[d.game_id != '2011_13_DET_NO']
s = d[(d.qb_scramble==1)&(d.play_type=='run')].copy()
print('\nscramble runs, all seasons:', len(s))
for c in ['passer_id','rusher_id','rusher_player_id','id']:
    if c in s:
        fm = s[c].dropna().str.match(PAT).mean() if s[c].notna().any() else "n/a"
        print(f'  {c}: blank {s[c].isna().sum()}, format examples {s[c].dropna().unique()[:3].tolist()}, matches 00-NNNNNNN: {fm}')
print('  passer_id == rusher_player_id (both present):', ((s.passer_id==s.rusher_player_id)&s.passer_id.notna()).sum(), 'of', (s.passer_id.notna()&s.rusher_player_id.notna()).sum())
smp = pd.concat([s[s.season==y].sample(15, random_state=7) for y in (2010, 2016, 2020, 2024)])
def desc_name(t):
    m = re.search(r'\d+-([A-Z][A-Za-z\'\.\- ]*?)\s+(scrambles|pass|sacked|up the|left|right|to )', str(t))
    return m.group(1).strip() if m else None
smp['desc_player'] = smp.desc.map(desc_name)
lk = lambda i: names.get(i) if (names is not None and isinstance(i, str)) else None
smp['passer_id_name'] = smp.passer_id.map(lk)
smp['rusher_id_name'] = smp.rusher_id.map(lk)
smp['rusher_player_id_name'] = smp.rusher_player_id.map(lk)
def same(full, short):
    if not isinstance(full, str) or not isinstance(short, str): return False
    ini, _, last = short.partition('.')
    f = full.replace('.', '').split()
    return len(f) >= 2 and last.replace(' ', '').lower() in ''.join(f[1:]).lower().replace("'", '').replace('-', '') or last.lower() in full.lower()
smp['passer_ok'] = [same(a, b) for a, b in zip(smp.passer_id_name, smp.desc_player)]
smp['rusher_ok'] = [same(a, b) for a, b in zip(smp.rusher_id_name, smp.desc_player)]
smp['rpid_ok'] = [same(a, b) for a, b in zip(smp.rusher_player_id_name, smp.desc_player)]
print('\nsample n =', len(smp), smp.season.value_counts().sort_index().to_dict())
print(smp[['season','desc_player','passer_id','passer_id_name','rusher_id','rusher_player_id','rusher_player_id_name','passer_ok','rpid_ok']].to_string(index=False))
print('\nshares: passer_id is scrambler', smp.passer_ok.mean(), '| rusher_id is scrambler', smp.rusher_ok.mean(), '| rusher_player_id is scrambler', smp.rpid_ok.mean())
print('passer_id ids not found in players table:', smp.passer_id_name.isna().sum())
bad = smp[~smp.passer_ok]
print('\nnon-matches:'); print(bad[['game_id','desc','passer_id_name']].to_string(index=False) if len(bad) else 'none')
# full-population check without name parsing: passer_id vs rusher_player_id
both = s.passer_id.notna() & s.rusher_player_id.notna()
print('\nfull population: passer_id == rusher_player_id on', round(100*(s.passer_id[both]==s.rusher_player_id[both]).mean(),3), '% of', both.sum(), 'scrambles with both')
mm = s[both & (s.passer_id != s.rusher_player_id)]
print('mismatches:', len(mm)); print(mm[['game_id','desc','passer','rusher_player_name']].head(10).to_string(index=False))
print('passer_id blank:', s.passer_id.isna().sum(), ' by season', s[s.passer_id.isna()].season.value_counts().sort_index().to_dict())
print(s[s.passer_id.isna()][['game_id','desc','rusher_player_id']].head(5).to_string(index=False))
