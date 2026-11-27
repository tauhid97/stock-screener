"""Checks for the screener math, using made-up prices (no internet needed).
Run: python test_screener.py
"""
from datetime import datetime

import pandas as pd

import screener as s

ET = s.ET


def fake_intraday(days, today_vol_mult, bars_today, price_today=110.0, open_today=104.0):
    """Each day has 78 five-minute bars of 1,000 shares. Today only has `bars_today` bars."""
    frames = []
    for i, d in enumerate(days):
        idx = pd.date_range(f"{d} 09:30", periods=78, freq="5min", tz=ET)
        vol, close, opn = 1000.0, 100.0, 100.0
        if i == len(days) - 1:
            idx = idx[:bars_today]
            vol, close, opn = 1000.0 * today_vol_mult, price_today, open_today
        df = pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": vol}, index=idx)
        df.iloc[0, df.columns.get_loc("Open")] = opn
        frames.append(df)
    return pd.concat(frames)


def fake_daily(n=200, last_day="2026-11-24", high=150.0, avg_vol=2_000_000):
    idx = pd.bdate_range(end=last_day, periods=n, tz=ET)
    df = pd.DataFrame({"Open": 100.0, "High": 100.0, "Low": 100.0, "Close": 100.0, "Volume": float(avg_vol)}, index=idx)
    df.iloc[-60, df.columns.get_loc("High")] = high  # the 6-month high, about 3 months ago
    return df


DAYS = [d.date().isoformat() for d in pd.bdate_range(end="2026-11-25", periods=8)]
INFO = {"symbol": "TEST", "name": "Test Co", "sector": "Tech"}


def test_relvol_by_time_of_day():
    # Today: 12 bars (first hour) at 2x the normal volume -> relvol 2.0, not 2.0 * 78/12
    rv, vol, last = s.relative_volume(fake_intraday(DAYS, 2.0, 12))
    assert abs(rv - 2.0) < 1e-9, rv
    assert vol == 24_000
    assert last.strftime("%H:%M") == "10:25"


def test_relvol_needs_history():
    assert s.relative_volume(fake_intraday(DAYS[-3:], 2.0, 12)) is None


def test_stock_row_numbers():
    row = s.stock_row(INFO, fake_daily(), fake_intraday(DAYS, 2.0, 12))
    assert row["price"] == 110.0
    assert row["change"] == 10.0      # 110 vs yesterday's 100
    assert row["gap"] == 4.0          # opened 104 vs 100
    assert row["relvol"] == 2.0
    assert row["off_high"] == round((110 / 150 - 1) * 100, 1)  # -26.7%


def test_lists():
    base = dict(name="x", sector="x", price=50, volume=1, avg_volume=1_000_000, gap=0, off_high=-5)
    rows = [
        dict(base, symbol="UPBUSY", change=2, relvol=3),
        dict(base, symbol="UPQUIET", change=2, relvol=1.2),
        dict(base, symbol="DOWNBUSY", change=-4, relvol=2, off_high=-30),
        dict(base, symbol="GAPPER", change=1, relvol=1, gap=-5),
        dict(base, symbol="CHEAP", change=5, relvol=9, price=3),
        dict(base, symbol="THIN", change=5, relvol=9, avg_volume=10_000),
    ]
    L = s.make_lists(rows)
    names = lambda k: [r["symbol"] for r in L[k]]
    assert names("up_busy") == ["UPBUSY"], names("up_busy")
    assert names("down_busy") == ["DOWNBUSY"]
    assert names("beaten_down") == ["DOWNBUSY"]
    assert names("big_gap") == ["GAPPER"]


def test_market_hours():
    assert s.market_is_open(datetime(2026, 11, 25, 10, 0, tzinfo=ET))
    assert s.market_is_open(datetime(2026, 11, 25, 16, 15, tzinfo=ET))
    assert not s.market_is_open(datetime(2026, 11, 25, 9, 0, tzinfo=ET))
    assert not s.market_is_open(datetime(2026, 11, 25, 17, 0, tzinfo=ET))
    assert not s.market_is_open(datetime(2026, 11, 28, 11, 0, tzinfo=ET))  # Saturday


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print("PASS", t.__name__)
    print(f"All {len(tests)} checks pass.")
