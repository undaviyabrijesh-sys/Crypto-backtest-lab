"""FVG demand / supply zone strategy (supply is the exact mirror of demand).

Zone     : 3-candle FVG. Demand = low[3rd] > high[1st]; supply = high[3rd] < low[1st].
           Zone = High-Low of the 1st candle.
Touch    : a candle trades into the zone. The candle with the lowest low (demand) /
           highest high (supply) in the touch sequence is the touch candle.
Confirm  : the NEXT candle closes above the touch candle's high (demand) / below its low (supply).
Entry    : at the close of the confirming candle = open of the following candle.
SL       : beyond the touch candle +/- buffer_pct, supplied to the engine via stops().
Big rule : if the confirming candle's range > big_mult x average range, skip it and enter when a
           later candle retraces `retrace` of that candle (within retrace_wait bars).
Zone dies: when price closes through it, when used once, or after max_zone_age bars.

Quality filters (to cut fee drag and noise; set to 0 to switch off):
  min_impulse : FVG middle candle range must be >= min_impulse x average range (real displacement).
  min_risk_pct: skip trades whose stop distance is below this % of price (tiny stops = fees eat the R).
  trend_len   : EMA length; longs only above the EMA, shorts only below it.
Not coded yet: BOS / IMP level filter.
"""
import numpy as np, pandas as pd

PARAMS = {
    "min_gap_pct": 0.0,    # minimum FVG size, % of price
    "min_impulse": 1.5,    # FVG middle candle >= this x avg range (0 = off)
    "min_risk_pct": 0.15,  # skip if stop distance < this % of price (0 = off)
    "trend_len": 0,        # EMA trend filter length (0 = off), e.g. 200
    "big_mult": 1.5,       # big closing candle = range > big_mult x avg range (14)
    "retrace": 0.5,        # retrace fraction of a big candle to enter
    "retrace_wait": 3,     # bars allowed for that retrace
    "buffer_pct": 0.02,    # SL buffer beyond touch candle, % of price
    "max_wait": 1,         # bars allowed between touch and confirmation
    "max_zone_age": 300,   # bars a zone stays alive
    "use_short": 1,        # 1 = also trade supply (short)
}
RISK = {"exit_on_signal": False}   # defaults the app applies for this strategy


def _build(df, p):
    p = {**PARAMS, **p}      # missing keys (e.g. an older paper config) fall back to defaults
    o, h, l, c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    n = len(df)
    avg = pd.Series(h - l).rolling(14).mean().shift(1).to_numpy()   # previous 14 bars only
    tl = int(p["trend_len"])
    ema = pd.Series(c).ewm(span=tl, adjust=False).mean().to_numpy() if tl > 0 else None
    sig, stp = np.zeros(n, dtype=int), np.zeros(n)
    zones, pend = [], []
    buf = p["buffer_pct"] / 100.0

    def ok(side, i, stop):
        """quality filters at the moment of entry (close of bar i)"""
        if abs(c[i] - stop) / c[i] * 100 < p["min_risk_pct"]:
            return False
        if ema is not None and ((c[i] <= ema[i]) if side == 1 else (c[i] >= ema[i])):
            return False
        return True

    for i in range(2, n):
        # ---- pending big-candle retrace entries
        for q in pend[:]:
            s = q["side"]
            if i - q["bar"] > int(p["retrace_wait"]) or (l[i] <= q["stop"] if s == 1 else h[i] >= q["stop"]):
                pend.remove(q)
            elif (l[i] <= q["level"]) if s == 1 else (h[i] >= q["level"]):
                if sig[i] == 0 and ok(s, i, q["stop"]):
                    sig[i], stp[i] = s, q["stop"]
                pend.remove(q)
        # ---- update live zones
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
            if (c[i] > h[t]) if s == 1 else (c[i] < l[t]):          # confirmation
                stop = l[t] * (1 - buf) if s == 1 else h[t] * (1 + buf)
                zones.remove(z)
                rng = h[i] - l[i]
                if not np.isnan(avg[i]) and rng > p["big_mult"] * avg[i]:
                    pend.append(dict(side=s, stop=stop, bar=i,
                                     level=c[i] - s * p["retrace"] * rng))
                elif sig[i] == 0 and ok(s, i, stop):
                    sig[i], stp[i] = s, stop
            elif (l[i] < l[t] and touched) if s == 1 else (h[i] > h[t] and touched):
                z["touch"], z["wait"] = i, 0                          # new extreme = new touch candle
            else:
                z["wait"] += 1
                if z["wait"] >= int(p["max_wait"]):
                    z["touch"] = None
        # ---- new FVG ending at bar i (zone becomes live from the next bar)
        if p["min_impulse"] > 0:
            mid_ok = (not np.isnan(avg[i - 1])) and (h[i - 1] - l[i - 1]) >= p["min_impulse"] * avg[i - 1]
        else:
            mid_ok = True
        if not mid_ok:
            continue
        gap_min = p["min_gap_pct"] / 100.0 * c[i]
        if l[i] - h[i - 2] > gap_min and l[i] > h[i - 2]:
            zones.append(dict(side=1, top=h[i - 2], bot=l[i - 2], born=i, touch=None, wait=0))
        elif p["use_short"] and l[i - 2] - h[i] > gap_min and h[i] < l[i - 2]:
            zones.append(dict(side=-1, top=h[i - 2], bot=l[i - 2], born=i, touch=None, wait=0))
    return sig, stp


def signals(df, p):
    return pd.Series(_build(df, p)[0], index=df.index)


def stops(df, p):
    return pd.Series(_build(df, p)[1], index=df.index)
