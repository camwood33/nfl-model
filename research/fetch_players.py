# Downloads the nflverse players table to data/historical/derived/dl_players/players.parquet (fixed path); input for the Amendment 7 and 8 scripts.
import os, urllib.request
URL = 'https://github.com/nflverse/nflverse-data/releases/download/players/players.parquet'
OUT = '/Users/cameronwood/nfl-model/data/historical/derived/dl_players/players.parquet'
os.makedirs(os.path.dirname(OUT), exist_ok=True)
urllib.request.urlretrieve(URL, OUT)
print('saved', OUT, os.path.getsize(OUT), 'bytes')
