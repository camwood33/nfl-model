"""
CLV summary statistics — per-bet and cumulative.
Consumed by the dashboard; can also be run standalone to export a CSV.

    python -m clv_tracker.summary [YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import CLV_ANALYSIS_DIR
from clv_tracker.db import get_all_bets, init_db

logger = logging.getLogger(__name__)


def compute_summary(
    game_date: str | date | None = None,
    model_version: str | None = None,
    since: str | None = None,
    game_date_start: str | None = None,
    game_date_end: str | None = None,
) -> dict:
    """
    Aggregate CLV stats across all bets that have a closing line.
    Filters to game_date, model_version, a logged_at >= since cutoff, and/or
    an inclusive game_date_start..game_date_end range (YYYY-MM-DD) when
    provided. The range is what the weekly/monthly Discord rollups use to
    scope a fixed calendar period.

    Returns a dict ready for JSON serialization or dashboard display:
      bets_with_closing     int
      total_bets            int
      mean_clv_raw          float — avg probability-point CLV
      mean_clv_pct          float — mean_clv_raw as percentage points
      mean_clv_log_odds     float | None
      pct_bets_positive_clv float — % of closed bets with CLV > 0
      by_market             list[dict] — breakdown per market type
      wins / losses         int
      total_pnl_dollars     float
      total_wagered_dollars float
      roi_pct               float
    """
    init_db()
    gd   = str(game_date) if game_date else None
    bets = get_all_bets(
        game_date=gd,
        model_version=model_version,
        since=since,
        game_date_start=game_date_start,
        game_date_end=game_date_end,
    )

    if not bets:
        return _empty_summary()

    df     = pd.DataFrame(bets)
    closed = df[df["closing_price"].notna() & (df["outcome"] != "void")].copy()

    if closed.empty:
        return _empty_summary(
            total_bets=len(df),
            total_wagered=float(df["bet_size_dollars"].sum()),
        )

    mean_clv_raw = float(closed["clv_raw"].mean())
    lo_vals      = closed["clv_log_odds"].dropna()
    mean_clv_lo  = float(lo_vals.mean()) if not lo_vals.empty else None
    pct_positive = float((closed["clv_raw"] > 0).mean() * 100)

    by_market = []
    for mkt, grp in df.groupby("market"):
        mkt_closed  = grp[grp["closing_price"].notna() & (grp["outcome"] != "void")]
        mkt_settled = grp[grp["outcome"].isin(["win", "loss"])]

        count       = len(mkt_closed)
        mean_clv    = round(float(mkt_closed["clv_raw"].mean()), 5) if count else None
        lo_sub      = mkt_closed["clv_log_odds"].dropna() if count else pd.Series(dtype=float)
        mean_clv_lo = round(float(lo_sub.mean()), 5) if not lo_sub.empty else None

        # "Flat" = clv_raw exactly 0.0 (genuine no-line-movement bets — entry_price ==
        # closing_price to the tick — not measurement noise; confirmed via the real
        # v2 distribution, which has a clean gap before the next nonzero cluster).
        pct_clv_positive = round(float((mkt_closed["clv_raw"] > 0).mean() * 100), 1) if count else None
        pct_clv_flat     = round(float((mkt_closed["clv_raw"] == 0.0).mean() * 100), 1) if count else None
        pct_clv_negative = round(float((mkt_closed["clv_raw"] < 0).mean() * 100), 1) if count else None

        wins    = int((mkt_settled["outcome"] == "win").sum())
        losses  = int((mkt_settled["outcome"] == "loss").sum())
        pnl     = round(float(mkt_settled["profit_loss"].sum()), 2) if not mkt_settled.empty else 0.0
        wagered = float(mkt_settled["bet_size_dollars"].sum()) if not mkt_settled.empty else 0.0
        roi     = round(pnl / wagered * 100, 2) if wagered > 0 else None

        sw_units = (
            mkt_settled[mkt_settled["unit_size"].notna()]
            if "unit_size" in mkt_settled.columns and not mkt_settled.empty
            else pd.DataFrame()
        )
        units_pnl = (
            round(float((sw_units["profit_loss"] / sw_units["unit_size"]).sum()), 2)
            if not sw_units.empty else None
        )

        by_market.append({
            "market_type":      mkt,
            "count":            count,
            "wins":             wins,
            "losses":           losses,
            "mean_clv":         mean_clv,
            "mean_clv_lo":      mean_clv_lo,
            "pct_clv_positive": pct_clv_positive,
            "pct_clv_flat":     pct_clv_flat,
            "pct_clv_negative": pct_clv_negative,
            "units_pnl":        units_pnl,
            "roi_pct":          roi,
            "total_pnl":        pnl,
        })

    has_outcome   = df[df["outcome"].isin(["win", "loss"])]
    wins          = int((has_outcome["outcome"] == "win").sum())
    losses        = int((has_outcome["outcome"] == "loss").sum())
    total_pnl     = float(has_outcome["profit_loss"].sum()) if not has_outcome.empty else 0.0
    total_wagered = float(has_outcome["bet_size_dollars"].sum())

    # Units +/-: sum of (profit_loss / unit_size) for settled bets that have unit_size logged.
    settled_with_units = (
        has_outcome[has_outcome["unit_size"].notna()]
        if "unit_size" in has_outcome.columns and not has_outcome.empty
        else pd.DataFrame()
    )
    units_pnl = (
        round(float((settled_with_units["profit_loss"] / settled_with_units["unit_size"]).sum()), 2)
        if not settled_with_units.empty
        else None
    )

    return {
        "bets_with_closing":      len(closed),
        "total_bets":             len(df),
        "mean_clv_raw":           round(mean_clv_raw, 5),
        "mean_clv_pct":           round(mean_clv_raw * 100, 3),
        "mean_clv_log_odds":      round(mean_clv_lo, 5) if mean_clv_lo is not None else None,
        "pct_bets_positive_clv":  round(pct_positive, 1),
        "by_market":              by_market,
        "wins":                   wins,
        "losses":                 losses,
        "total_pnl_dollars":      round(total_pnl, 2),
        "total_wagered_dollars":  round(total_wagered, 2),
        "roi_pct":                round(total_pnl / total_wagered * 100, 2)
                                  if total_wagered > 0 else 0.0,
        "units_pnl":              units_pnl,
    }


def _empty_summary(total_bets: int = 0, total_wagered: float = 0.0) -> dict:
    return {
        "bets_with_closing": 0, "total_bets": total_bets,
        "mean_clv_raw": 0.0, "mean_clv_pct": 0.0, "mean_clv_log_odds": None,
        "pct_bets_positive_clv": 0.0, "by_market": [],
        "wins": 0, "losses": 0,
        "total_pnl_dollars": 0.0,
        "total_wagered_dollars": round(total_wagered, 2),
        "roi_pct": 0.0,
        "units_pnl": None,
    }


def export_csv(out_dir: Path | None = None) -> pd.DataFrame:
    """
    Write a flat CSV of all bets (with CLV columns) to clv_tracker/analysis/.
    Filename: clv_summary_YYYY-MM-DD.csv (today's date).
    Returns the DataFrame.
    """
    init_db()
    bets = get_all_bets()
    if not bets:
        logger.info("No bets to export.")
        return pd.DataFrame()

    df     = pd.DataFrame(bets)
    target = Path(out_dir) if out_dir else CLV_ANALYSIS_DIR
    target.mkdir(parents=True, exist_ok=True)
    out = target / f"clv_summary_{date.today().isoformat()}.csv"
    df.to_csv(out, index=False)
    logger.info("Exported %d bet rows → %s", len(df), out)
    return df


# ── CLI entry point ───────────────────────────────────────────────────────────

def _cli():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Print CLV summary statistics.")
    p.add_argument("game_date", nargs="?", default=None,
                   help="YYYY-MM-DD — omit for all-time stats.")
    p.add_argument("--export", action="store_true",
                   help="Also write clv_tracker/analysis/clv_summary_<today>.csv.")
    args = p.parse_args()

    s = compute_summary(game_date=args.game_date)
    print(f"\n{'='*48}")
    label = f"  —  {args.game_date}" if args.game_date else "  (all-time)"
    print(f"  CLV SUMMARY{label}")
    print(f"{'='*48}")
    print(f"  Bets logged:        {s['total_bets']}")
    print(f"  Closing lines set:  {s['bets_with_closing']}")
    lo_str = (f"  ({s['mean_clv_log_odds']:+.4f} lo)"
              if s["mean_clv_log_odds"] is not None else "")
    print(f"  Mean CLV:           {s['mean_clv_pct']:+.3f} pp{lo_str}")
    print(f"  % positive CLV:     {s['pct_bets_positive_clv']:.1f}%")
    print(f"  W / L:              {s['wins']} / {s['losses']}")
    print(f"  Total wagered:      ${s['total_wagered_dollars']:,.2f}")
    print(f"  P&L:                ${s['total_pnl_dollars']:+,.2f}  (ROI {s['roi_pct']:+.2f}%)")
    if s["by_market"]:
        print(f"\n  By market:")
        for row in s["by_market"]:
            print(f"    {row['market_type']:20s}  n={row['count']}  "
                  f"mean CLV {row['mean_clv'] * 100:+.3f} pp")
    print()

    if args.export:
        export_csv()


if __name__ == "__main__":
    _cli()
