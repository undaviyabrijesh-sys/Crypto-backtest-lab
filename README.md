# Crypto Backtest Lab

Backtest + paper-trade (forward test) crypto strategies written in Python, with a dark Streamlit dashboard.

## Setup
1. Push this folder to a new GitHub repo.
2. Actions tab -> run **update-data** once (fills `data/`), then **paper-trade** once (starts forward test).
3. Deploy the dashboard free at https://share.streamlit.io (main file: `app.py`).
   Keep the app private: it executes uploaded Python.

## Strategy format (`strategies/*.py`)
```python
PARAMS = {"ema": 21}            # become sidebar inputs automatically

def signals(df, p):             # df: open/high/low/close/volume, time index
    ...                         # return +1 long, -1 short, 0 flat per bar
```
Upload a `.py` in the sidebar to test it, or commit it to `strategies/` to keep it.
A trade is opened when the signal CHANGES into +1/-1 (edge), so level-type signals work too.

### Optional extras a strategy file can define
- `stops(df, p)` -> Series of stop PRICES on signal bars (e.g. beyond the touch candle). The engine then uses
  that stop instead of the fixed SL input, and TP1/TP2 become multiples of that distance.
- `RISK = {"exit_on_signal": False}` -> default risk settings the app applies for this strategy.
  (Event-type signals that fire for one bar should have exit_on_signal off, otherwise the trade closes next bar.)
- For paper trading, `paper/config.json -> risk` overrides these, so set `exit_on_signal` there too.

### Included strategies
- `ema.py` - 21 EMA trend follower (simple demo).
- `fvg_zone.py` - FVG demand/supply zones: touch candle, confirmation close, SL beyond touch candle,
  big-candle retrace rule. Supply = mirror of demand. BOS / IMP filter not coded yet.

## Engines (sidebar -> Risk)
**SL / TP (2 lots)** - event-driven, uses candle high/low:
- SL in points or %, TP1 and TP2 as multiples of SL (default 1R and 2R).
- Lot 1 (default 50%) books at TP1. When TP1 hits, lot 2's SL moves to cost (toggle).
- Optional exit of remaining lots when the signal flips.
- Same-candle SL+TP -> SL assumed first (conservative). Stops gap-fill at the open.

**Signal only** - holds the signal position bar by bar, no SL/TP.

## Optimizer tab
Sweeps SL vs TP2 and shows a heatmap of the chosen metric. Prefer broad plateaus over a single best cell.

## Paper trading
Edit `paper/config.json` (exchange, symbol, timeframe, strategy, params, risk). It runs every 15 min
via GitHub Actions using the SAME engine as the backtest, and logs to `paper/equity.csv`,
`paper/trades.csv`, `paper/state.json`. To restart or change settings cleanly, delete those three files.

## Notes
- Default exchange is `binanceus` (GitHub runners are in the US). Change `EXCHANGE` in `data.py` and `exchange` in `paper/config.json` if needed.
- Entries fill at the signal candle's close. Fees are charged on every fill; no slippage model yet.
