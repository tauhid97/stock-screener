# Boss's Stock Screener

A free, Finviz-style stock screener of our own.

- **Page:** https://tauhid97.github.io/stock-screener
- **What it checks:** about 500 big US stocks (S&P 500), every 15 minutes while the market is open (9:30 am - 4:30 pm New York time).
- **Data:** free Yahoo prices via `yfinance`, about 15 minutes late. All numbers are worked out in `screener.py`.

## The 4 lists
1. 🟢 **Up + busy**: up today, volume 1.5x normal for this time of day
2. 🔴 **Down + busy**: down today, volume 1.5x normal for this time of day
3. 🪫 **Beaten-down + waking up**: 20%+ below the 6-month high, volume 1.5x normal
4. ⚡ **Big gap**: opened 3%+ above or below yesterday's close

Only stocks over $5 that trade at least 500k shares a day on average are shown.

## Files
- `screener.py`: gets prices, works out the numbers, writes `docs/data.json`
- `test_screener.py`: checks the math with made-up prices
- `data/tickers.csv`: the stock list
- `docs/index.html`: the web page
- `.github/workflows/screener.yml`: the 15-minute timer (GitHub Actions, free on public repos)

**Information only. Not advice. It never buys or sells anything.**
