from pathlib import Path

BASE_DIR = Path(__file__).parent

# Data paths
RAW_DATA_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DATA_DIR = BASE_DIR / "data" / "processed"
HISTORICAL_DATA_DIR = BASE_DIR / "data" / "historical"

# Output paths
PICKS_DIR = BASE_DIR / "outputs" / "picks"
REPORTS_DIR = BASE_DIR / "outputs" / "reports"
LOGS_DIR = BASE_DIR / "outputs" / "logs"

# CLV tracker paths
CLV_RECORDS_DIR = BASE_DIR / "clv_tracker" / "records"
CLV_ANALYSIS_DIR = BASE_DIR / "clv_tracker" / "analysis"

# API keys (replace with your credentials or load from environment)
ODDS_API_KEY = ""
STATS_API_KEY = ""

# --- PLACEHOLDER VALUES BELOW ---
# These are copied from MLB's starting point ONLY so this file runs.
# None of these are real decisions for NFL yet. Every one of these must be
# re-derived from actual NFL backtest results (bet variance, edge distribution,
# price behavior across all six markets) before any real logic depends on them.
BANKROLL = 1000.0
MAX_KELLY_FRACTION = 0.25   # PLACEHOLDER — revisit after backtest
MIN_EDGE_THRESHOLD = 0.03   # PLACEHOLDER — revisit after backtest
UNIT_DIVISOR = 50            # PLACEHOLDER — revisit after backtest
MAX_BET_UNITS = 2            # PLACEHOLDER — revisit after backtest
MAX_DAILY_BETS = 5           # PLACEHOLDER — revisit after backtest
PAPER_BETTING_MODE = True    # Stays True until NFL earns real-money trust, same as MLB did

# Public-launch cutoff — not applicable yet, no NFL public launch has happened
PUBLIC_LAUNCH_DATE = None

# Discord notifications — OFF until NFL's actual webhook/channel infrastructure
# is built and tested. Do not flip to True by copying MLB's file blindly.
DISCORD_NOTIFICATIONS_ENABLED = False
DISCORD_RESULTS_NOTIFICATIONS_ENABLED = False
DISCORD_WEEKLY_NOTIFICATIONS_ENABLED = False
DISCORD_MONTHLY_NOTIFICATIONS_ENABLED = False

# Auto-log bets — OFF until the full pipeline is built and verified working.
# Turning this on prematurely means bets could auto-log before logic is trusted.
AUTO_LOG_BETS_ENABLED = False
