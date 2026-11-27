"""Boss's Stock Screener.

Checks about 500 big US stocks (S&P 500) with free Yahoo data (about 15 minutes late),
works out the numbers itself, and writes docs/data.json for the web page.
Information only: it never buys or sells anything.

Run:  python screener.py          (only updates while the market is open)
      python screener.py --force  (updates any time, using the latest market day)
"""
import argparse
import csv
import json
import math
import sys
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).parent
TICKERS_FILE = ROOT / "data" / "tickers.csv"
OUT_FILE = ROOT / "docs" / "data.json"

# ---- Settings (easy to change) ----
MIN_PRICE = 5.0            # skip stocks under $5
MIN_AVG_VOLUME = 500_000   # skip stocks that trade under 500k shares a day on average
BUSY_RELVOL = 1.5          # "busy" = volume 1.5x normal for this time of day
BEATEN_DOWN = 0.20         # 20%+ below the 6-month high
BIG_GAP = 0.03             # opened 3%+ above or below yesterday's close
SIX_MONTHS = 126           # trading days in about 6 months
RELVOL_DAYS = 10           # compare today with up to the last 10 market days
MAX_ROWS = 50              # longest list shown per tab


def load_tickers():
    with open(TICKERS_FILE) as f:
        return [r for r in csv.DictReader(f)]


def market_is_open(now_et):
    """True on weekdays between 9:30 and 16:30 New York time (16:30 = one last update after the close)."""
    return now_et.weekday() < 5 and time(9, 30) <= now_et.time() <= time(16, 30)


def relative_volume(intraday):
    """Today's volume so far compared with the normal volume by the same time of day.

    intraday: DataFrame with a New-York-time index and a 'Volume' column (5-minute bars).
    Returns (relvol, today_volume, last_bar_time) or None if there is not enough data.
    """
    bars = intraday.dropna(subset=["Volume"])
    bars = bars[bars["Volume"] >= 0]
    if bars.empty:
        return None
    days = sorted(set(bars.index.date))
    today = days[-1]
    today_bars = bars[bars.index.date == today]
    cutoff = today_bars.index[-1].time()
    today_vol = float(today_bars["Volume"].sum())
    past = []
    for d in days[:-1][-RELVOL_DAYS:]:
        day_bars = bars[bars.index.date == d]
        v = float(day_bars[[t <= cutoff for t in day_bars.index.time]]["Volume"].sum())
        if v > 0:
            past.append(v)
    if len(past) < 3:
        return None
    normal = sum(past) / len(past)
    return today_vol / normal, today_vol, today_bars.index[-1]


def stock_row(info, daily, intraday):
    """Work out all the numbers for one stock. Returns a dict, or None if data is missing."""
    daily = daily.dropna(subset=["Close"])
    intraday = intraday.dropna(subset=["Close"])
    if len(daily) < 30 or intraday.empty:
        return None
    rv = relative_volume(intraday)
    if rv is None:
        return None
    relvol, today_vol, last_bar = rv
    today = last_bar.date()
    today_bars = intraday[intraday.index.date == today]
    price = float(today_bars["Close"].iloc[-1])
    day_open = float(today_bars["Open"].iloc[0])

    before = daily[[d < today for d in daily.index.date]]
    if len(before) < 20:
        return None
    prev_close = float(before["Close"].iloc[-1])
    avg_vol = float(before["Volume"].tail(50).mean())
    high_6m = max(float(before["High"].tail(SIX_MONTHS - 1).max()), float(today_bars["High"].max()))

    if not all(map(math.isfinite, [price, day_open, prev_close, avg_vol, high_6m])) or prev_close <= 0:
        return None
    return {
        "symbol": info["symbol"],
        "name": info["name"],
        "sector": info["sector"],
        "price": round(price, 2),
        "change": round((price / prev_close - 1) * 100, 2),
        "gap": round((day_open / prev_close - 1) * 100, 2),
        "relvol": round(relvol, 2),
        "volume": int(today_vol),
        "avg_volume": int(avg_vol),
        "off_high": round((price / high_6m - 1) * 100, 1),
        "_date": today.isoformat(),
        "_time": last_bar.strftime("%H:%M"),
    }


def make_lists(rows):
    """Split the stocks into Boss's 4 lists."""
    ok = [r for r in rows if r["price"] >= MIN_PRICE and r["avg_volume"] >= MIN_AVG_VOLUME]
    busy = [r for r in ok if r["relvol"] >= BUSY_RELVOL]
    by_relvol = lambda r: -r["relvol"]
    return {
        "up_busy": sorted([r for r in busy if r["change"] > 0], key=by_relvol)[:MAX_ROWS],
        "down_busy": sorted([r for r in busy if r["change"] < 0], key=by_relvol)[:MAX_ROWS],
        "beaten_down": sorted([r for r in busy if r["off_high"] <= -BEATEN_DOWN * 100], key=by_relvol)[:MAX_ROWS],
        "big_gap": sorted([r for r in ok if abs(r["gap"]) >= BIG_GAP * 100], key=lambda r: -abs(r["gap"]))[:MAX_ROWS],
    }


def _fetch(symbols, **kw):
    """Download in groups of 100 (Yahoo is happier that way), then retry any that failed once."""
    import yfinance as yf
    common = dict(group_by="ticker", auto_adjust=False, threads=True, progress=False, timeout=20)
    parts = []
    for i in range(0, len(symbols), 100):
        parts.append(yf.download(symbols[i:i + 100], **common, **kw))
    df = pd.concat(parts, axis=1)
    got = {s for s in df.columns.get_level_values(0) if not df[s]["Close"].dropna().empty}
    retry = [s for s in symbols if s not in got]
    if retry:
        again = yf.download(retry, **common, **kw)
        if not isinstance(again.columns, pd.MultiIndex):  # a single stock comes back flat
            again = pd.concat({retry[0]: again}, axis=1)
        keep = [s for s in again.columns.get_level_values(0).unique() if not again[s]["Close"].dropna().empty]
        df = pd.concat([df.drop(columns=keep, level=0, errors="ignore"), again[keep]], axis=1)
    return df


def download(symbols):
    daily = _fetch(symbols, period="1y", interval="1d")
    intraday = _fetch(symbols, period=f"{RELVOL_DAYS + 5}d", interval="5m", prepost=False)
    if intraday.index.tz is None:
        intraday.index = intraday.index.tz_localize("UTC")
    intraday.index = intraday.index.tz_convert(ET)
    return daily, intraday


def run(force=False):
    now = datetime.now(ET)
    if not force and not market_is_open(now):
        print(f"Market closed ({now:%a %H:%M} New York). Nothing to do.")
        return 0
    tickers = load_tickers()
    symbols = [t["symbol"] for t in tickers]
    print(f"Checking {len(symbols)} stocks...")
    daily, intraday = download(symbols)

    rows, missing = [], []
    for info in tickers:
        s = info["symbol"]
        try:
            row = stock_row(info, daily[s], intraday[s])
        except KeyError:
            row = None
        (rows.append(row) if row else missing.append(s))
    if len(rows) < 100:
        print(f"Only {len(rows)} stocks came back from Yahoo. Not updating the page.")
        return 1

    session = max(r["_date"] for r in rows)
    if not force and session != now.date().isoformat():
        print(f"No trading today (latest data is {session}), probably a holiday. Nothing to do.")
        return 0
    rows = [r for r in rows if r["_date"] == session]
    data_time = max(r["_time"] for r in rows)
    for r in rows:
        r.pop("_date"), r.pop("_time")

    lists = make_lists(rows)
    out = {
        "updated": now.strftime("%Y-%m-%d %H:%M ET"),
        "session": session,
        "data_time": data_time,
        "checked": len(rows),
        "missing": len(missing),
        "settings": {
            "busy_relvol": BUSY_RELVOL, "beaten_down_pct": BEATEN_DOWN * 100,
            "big_gap_pct": BIG_GAP * 100, "min_price": MIN_PRICE, "min_avg_volume": MIN_AVG_VOLUME,
        },
        "lists": lists,
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, indent=1))
    print(f"Done: {len(rows)} stocks checked ({len(missing)} missing). Data up to {session} {data_time} ET.")
    for k, v in lists.items():
        print(f"  {k}: {len(v)} stocks" + (f" (top: {v[0]['symbol']})" if v else ""))
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="update even when the market is closed")
    sys.exit(run(force=p.parse_args().force))
