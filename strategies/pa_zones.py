"""Price action + demand/supply strategy, built as four modules.

1. STRUCTURE  : swing highs/lows (swing_len bars each side). A close above the last swing high = bullish BOS
                (bias +1); a close below the last swing low = bearish BOS (bias -1).
                With use_structure=1 only longs trade in a bullish bias, only shorts in a bearish bias.
2. ZONES      : 3-candle FVG with a real impulse candle in the middle. Demand: low[3rd] > high[1st];
                supply: high[3rd] < low[1st]. Zone = High-Low of the 1st candle. Supply = mirror of demand.
3. ENTRY      : price touches the zone; the touch candle is the extreme one (lowest low for demand);
                the NEXT candle must close beyond the touch candle (above its high / below its low).
                Entry at that close. If that candle is big, wait for a pullback (retrace) instead.
4. SL / TP    : SL = beyond the touch candle +/- buffer. Targets: Target 1 / Target 2 are R multiples set in the
                sidebar. With tp_mode=1, Target 2 becomes the previous swing high (long) / low (short)
                when that is at least Target 1 away.
Not coded yet: IMP level, equal-highs liquidity targets.
"""
import hashlib
import numpy as np, pandas as pd

PARAMS = {
    "swing_len": 5,        # bars each side that define a swing high/low
    "use_structure": 1,    # 1 = trade only with the BOS bias
    "min_impulse": 1.5,    # FVG middle candle >= this x average candle (0 = off)
    "min_gap_pct": 0.0,    # minimum FVG size, % of price
    "max_zone_age": 300,   # bars a zone stays alive
    "max_wait": 1,         # bars allowed between touch and confirmation
    "big_mult": 1.5,       # confirming candle bigger than this x average = wait for pullback
    "retrace": 0.5,        # pullback fraction of that big candle
    "retrace_wait": 3,     # bars allowed for the pullback
    "buffer_pct": 0.02,    # SL buffer beyond touch candle, % of price
    "min_risk_pct": 0.15,  # skip trades whose stop is closer than this % of price (fees)
    "tp_mode": 0,          # 0 = Target 2 from sidebar R multiple, 1 = previous swing high/low
    "use_short": 1,        # 1 = also trade supply (short)
}
RISK = {"exit_on_signal": False}

PARAM_INFO = {
    "swing_len": {"label": "Swing size (bars each side)", "help": "How many candles each side make a swing high/low. Bigger = fewer, more important swings."},
    "use_structure": {"label": "Trade only with structure (1 = yes)", "help": "Longs only after a bullish BOS, shorts only after a bearish BOS."},
    "min_impulse": {"label": "Impulse strength (x avg candle)", "help": "The big middle candle of the FVG must be at least this many times the average candle. 0 = off.", "step": 0.1},
    "min_gap_pct": {"label": "Min gap size (% of price)", "help": "Ignore tiny FVGs. Try 0.02 to 0.08.", "step": 0.01},
    "max_zone_age": {"label": "Zone lifetime (bars)", "help": "A zone is forgotten after this many candles."},
    "max_wait": {"label": "Bars allowed to confirm", "help": "1 = the very next candle after the touch must confirm."},
    "big_mult": {"label": "Big candle = x avg candle", "help": "If the confirming candle is bigger, wait for a pullback instead of entering at once.", "step": 0.1},
    "retrace": {"label": "Pullback needed after big candle", "help": "0.5 = wait for half of the big candle to be given back.", "step": 0.05},
    "retrace_wait": {"label": "Bars to wait for that pullback", "help": "No pullback within this many candles = trade cancelled."},
    "buffer_pct": {"label": "Stop buffer (% of price)", "help": "Extra room beyond the touch candle for the stop.", "step": 0.01},
    "min_risk_pct": {"label": "Min stop distance (% of price)", "help": "Skip trades with tiny stops; fees would eat the profit. 0 = off.", "step": 0.05},
    "tp_mode": {"label": "Target 2 mode (0 = R multiple, 1 = previous swing)", "help": "1 aims lot 2 at the previous swing high (long) / low (short) if it is far enough."},
    "use_short": {"label": "Also trade shorts (1 = yes)", "help": "Supply zones = mirror of demand."},
}

OPTIMIZE = {
    "swing_len": [3, 5, 8],
    "min_impulse": [0, 1.0, 1.5, 2.0, 2.5],
    "min_gap_pct": [0, 0.02, 0.04, 0.08],
    "min_risk_pct": [0.1, 0.15, 0.2, 0.3, 0.4],
    "big_mult": [1.2, 1.5, 2.0, 3.0],
    "retrace": [0.382, 0.5, 0.618],
    "buffer_pct": [0.01, 0.02, 0.05],
    "tp_mode": [0, 1],
}

_CACHE = {}


def _build(df, p):
    p = {**PARAMS, **p}
    fp = hashlib.md5(df[["high", "low", "close"]].to_numpy(dtype=float).tobytes()).hexdigest()
    key = (fp, tuple(sorted(p.items())))          # keyed on the actual prices, not just dates/length
    if key in _CACHE:
        return _CACHE[key]
    h, l, c = (df[k].to_numpy(dtype=float) for k in ("high", "low", "close"))
    n = len(df)
    N = max(1, int(p["swing_len"]))
    avg = pd.Series(h - l).rolling(14).mean().shift(1).to_numpy()
    sig, stp, tpx = np.zeros(n, dtype=int), np.zeros(n), np.zeros(n)
    sh, sl_ = [], []                      # confirmed swing highs / lows (prices)
    bias = 0
    zones, pend = [], []
    buf = p["buffer_pct"] / 100.0

    def target(s, price):                 # most recent swing beyond the entry price
        for lvl in reversed(sh if s == 1 else sl_):
            if (lvl > price) if s == 1 else (lvl < price):
                return lvl
        return 0.0

    def ok(s, i, stop):
        if abs(c[i] - stop) / c[i] * 100 < p["min_risk_pct"]:
            return False
        return (not p["use_structure"]) or bias == s

    def fire(s, i, stop):
        sig[i], stp[i] = s, stop
        tpx[i] = target(s, c[i]) if p["tp_mode"] == 1 else 0.0

    for i in range(2, n):
        # ---- 1. structure: confirm swings (no look-ahead) and update BOS bias
        j = i - N
        if j >= N:
            if h[j] > h[j - N:j].max() and h[j] >= h[j + 1:i + 1].max():
                sh.append(h[j])
            if l[j] < l[j - N:j].min() and l[j] <= l[j + 1:i + 1].min():
                sl_.append(l[j])
        if sh and c[i] > sh[-1]:
            bias = 1
        elif sl_ and c[i] < sl_[-1]:
            bias = -1
        # ---- 3b. pending big-candle pullback entries
        for q in pend[:]:
            s = q["side"]
            if i - q["bar"] > int(p["retrace_wait"]) or (l[i] <= q["stop"] if s == 1 else h[i] >= q["stop"]):
                pend.remove(q)
            elif (l[i] <= q["level"]) if s == 1 else (h[i] >= q["level"]):
                if sig[i] == 0 and ok(s, i, q["stop"]):
                    fire(s, i, q["stop"])
                pend.remove(q)
        # ---- 3. entry module: touch -> confirm
        for z in zones[:]:
            s = z["side"]
            if i - z["born"] > int(p["max_zone_age"]) or (c[i] < z["bot"] if s == 1 else c[i] > z["top"]):
                zones.remove(z)
                continue
            touched = (l[i] <= z["top"]) if s == 1 else (h[i] >= z["bot"])
            t = z["touch"]
            if t is None:
                if touched:
                    z["touch"], z["wait"] = i, 0
                continue
            if (c[i] > h[t]) if s == 1 else (c[i] < l[t]):
                stop = l[t] * (1 - buf) if s == 1 else h[t] * (1 + buf)
                zones.remove(z)
                rng = h[i] - l[i]
                if not np.isnan(avg[i]) and rng > p["big_mult"] * avg[i]:
                    pend.append(dict(side=s, stop=stop, bar=i, level=c[i] - s * p["retrace"] * rng))
                elif sig[i] == 0 and ok(s, i, stop):
                    fire(s, i, stop)
            elif (l[i] < l[t] and touched) if s == 1 else (h[i] > h[t] and touched):
                z["touch"], z["wait"] = i, 0
            else:
                z["wait"] += 1
                if z["wait"] >= int(p["max_wait"]):
                    z["touch"] = None
        # ---- 2. zone module: new FVG ending at bar i (live from the next bar)
        if p["min_impulse"] > 0:
            if np.isnan(avg[i - 1]) or (h[i - 1] - l[i - 1]) < p["min_impulse"] * avg[i - 1]:
                continue
        gap_min = p["min_gap_pct"] / 100.0 * c[i]
        up = l[i] - h[i - 2] > gap_min and l[i] > h[i - 2]
        dn = l[i - 2] - h[i] > gap_min and h[i] < l[i - 2]
        if up and ((not p["use_structure"]) or bias == 1):
            zones.append(dict(side=1, top=h[i - 2], bot=l[i - 2], born=i, touch=None, wait=0))
        elif dn and p["use_short"] and ((not p["use_structure"]) or bias == -1):
            zones.append(dict(side=-1, top=h[i - 2], bot=l[i - 2], born=i, touch=None, wait=0))
    if len(_CACHE) > 8:
        _CACHE.clear()
    _CACHE[key] = (sig, stp, tpx)
    return sig, stp, tpx


def signals(df, p):
    return pd.Series(_build(df, p)[0], index=df.index)


def stops(df, p):
    """Stop price and (optional) Target-2 price on signal bars."""
    _, stp, tpx = _build(df, p)
    return pd.DataFrame({"sl": stp, "tp": tpx}, index=df.index)
