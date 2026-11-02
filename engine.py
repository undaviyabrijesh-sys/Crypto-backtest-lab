"""Backtest engines.

run(df, signal, fee, risk=None, slp=None)
  risk=None  -> "Signal only": hold the signal position, trade at candle close.
  risk=dict  -> "SL / TP (2 lots)": event-driven, intrabar SL/TP using candle high/low.
  slp        -> optional Series of stop prices, or DataFrame with columns "sl" (stop price) and
                "tp" (Target-2 price), supplied by the strategy on signal bars.

Rules of the SL/TP engine
- Entry at the CLOSE of the bar where the signal changes into +1/-1 (edge, not level).
- Total size = 100% of equity, split into lot 1 (lot1_pct) and lot 2 (rest).
- SL for both lots = entry -/+ SL distance. TP1 (lot 1) and TP2 (lot 2) are multiples of the SL distance
  (TP2 can be a strategy-supplied price if it is at least TP1 away).
- When TP1 is hit, lot 1 books and (if tsl) lot 2's SL moves to cost (entry).
- If one candle touches both SL and TP, SL is assumed first (conservative).
- Gaps: stops fill at the open if the open is already beyond the stop.
- exit_on_signal: close remaining lots at the close when the signal changes/flattens.
"""
import numpy as np, pandas as pd

DEFAULT_RISK = dict(sl_mode="%", sl=0.5, tp1_r=1.0, tp2_r=2.0,
                    lot1_pct=50, tsl=True, exit_on_signal=True)


def new_state(eq=1.0):
    return dict(dir=0, entry=0.0, w1=0.0, w2=0.0, sl1=0.0, sl2=0.0, tp1=0.0, tp2=0.0,
                risk=0.0, real=0.0, base=float(eq), t0=None, moved=False, rs=[])


def _finish(st, t):
    d = st["dir"]
    tr = {"entry_time": st["t0"], "exit_time": str(t),
          "side": "LONG" if d == 1 else "SHORT",
          "entry": round(st["entry"], 4), "exit": "+".join(st["rs"]),
          "pnl_%": round(st["real"] * 100, 3),
          "R": round(st["real"] / st["risk"], 2) if st["risk"] else 0.0}
    st["base"] *= 1 + st["real"]
    tr["equity"] = st["base"]
    st.update(dir=0, w1=0.0, w2=0.0, real=0.0, rs=[], moved=False)
    return tr


def step(st, t, o, h, l, c, sig, prev, rk, fee, slp=0.0, tpx=0.0):
    """Advance one CLOSED candle. Returns (mark-to-market equity, closed_trade_or_None, entered_bool)."""
    closed = None
    d = st["dir"]
    if d:
        e = st["entry"]

        def stop_hit(px):
            return l <= px if d == 1 else h >= px

        def tp_hit(px):
            return h >= px if d == 1 else l <= px

        def close(k, px, why):
            w = st[k]
            st["real"] += w * d * (px / e - 1) - w * fee
            st[k] = 0.0
            st["rs"].append(why)

        def stop_fill(px):
            return min(o, px) if d == 1 else max(o, px)

        def tp_fill(px):
            return max(o, px) if d == 1 else min(o, px)

        if st["w1"] and stop_hit(st["sl1"]):
            close("w1", stop_fill(st["sl1"]), "SL")
        if st["w2"] and stop_hit(st["sl2"]):
            close("w2", stop_fill(st["sl2"]), "TSL" if st["moved"] else "SL")
        if st["w1"] and tp_hit(st["tp1"]):
            close("w1", tp_fill(st["tp1"]), "TP1")
            if rk["tsl"] and st["w2"]:
                st["sl2"], st["moved"] = e, True
                if stop_hit(e):
                    close("w2", e, "TSL")
        if st["w2"] and tp_hit(st["tp2"]):
            close("w2", tp_fill(st["tp2"]), "TP2")

        if not st["w1"] and not st["w2"]:
            closed = _finish(st, t)
        elif rk["exit_on_signal"] and sig != d:
            for k in ("w1", "w2"):
                if st[k]:
                    close(k, c, "SIG")
            closed = _finish(st, t)

    entered = False
    if st["dir"] == 0 and sig != 0 and sig != prev:
        s = int(sig)
        if slp:   # strategy-supplied stop price (must be on the correct side of the entry)
            dist = abs(c - slp) if ((slp < c) if s == 1 else (slp > c)) else 0.0
        else:
            dist = rk["sl"] if rk["sl_mode"] == "points" else c * rk["sl"] / 100.0
        if dist > 0:
            w1 = min(max(rk["lot1_pct"], 0), 100) / 100.0
            tp2 = c + s * rk["tp2_r"] * dist
            if tpx and ((tpx > c) if s == 1 else (tpx < c)) and abs(tpx - c) >= rk["tp1_r"] * dist:
                tp2 = tpx             # strategy-supplied target (e.g. previous swing)
            st.update(dir=s, entry=float(c), w1=w1, w2=1.0 - w1,
                      sl1=c - s * dist, sl2=c - s * dist,
                      tp1=c + s * rk["tp1_r"] * dist, tp2=tp2,
                      risk=dist / c, real=-fee, t0=str(t), moved=False, rs=[])
            entered = True

    d = st["dir"]
    if d:
        eq = st["base"] * (1 + st["real"] + (st["w1"] + st["w2"]) * d * (c / st["entry"] - 1))
    else:
        eq = st["base"]
    return eq, closed, entered


def _sharpe(strat, df):
    step_s = df.index.to_series().diff().median().total_seconds()
    bpy = 365 * 86400 / step_s
    return strat.mean() / strat.std() * np.sqrt(bpy) if strat.std() > 0 else 0.0


def run_simple(df, pos, fee=0.0006):
    pos = pd.Series(pos, index=df.index).fillna(0).clip(-1, 1)
    p = pos.shift(1).fillna(0)            # trade on next bar
    ret = df["close"].pct_change().fillna(0)
    strat = p * ret - p.diff().abs().fillna(0) * fee
    eq = (1 + strat).cumprod()
    bh = (1 + ret).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    grp = (p != p.shift()).cumsum()[p != 0]
    t = strat[p != 0].groupby(grp).sum()
    trades = pd.DataFrame({"pnl_%": (t * 100).round(2)})
    stats = {
        "Return %": round((eq.iloc[-1] - 1) * 100, 1),
        "Max DD %": round(dd * 100, 1),
        "Sharpe": round(_sharpe(strat, df), 2),
        "Trades": len(t),
        "Win rate %": round((t > 0).mean() * 100, 1) if len(t) else 0,
    }
    return dict(stats=stats, equity=eq, bh=bh, trades=trades, pos=pos, strat=strat)


def run_sltp(df, sig, fee, rk, slp=None):
    rk = {**DEFAULT_RISK, **rk}
    TPX = np.zeros(len(df))
    if slp is None:
        SLP = np.zeros(len(df))
    elif isinstance(slp, pd.DataFrame):          # columns: "sl" (stop price), "tp" (target-2 price)
        lv = slp.reindex(df.index).fillna(0)
        SLP, TPX = lv["sl"].to_numpy(dtype=float), lv["tp"].to_numpy(dtype=float)
    else:
        SLP = pd.Series(slp, index=df.index).fillna(0).to_numpy(dtype=float)
    sig = pd.Series(sig, index=df.index).fillna(0).clip(-1, 1).astype(int)
    prev = sig.shift(1).fillna(0).astype(int)
    O, H, L, C = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    S, PV = sig.to_numpy(), prev.to_numpy()
    st = new_state(1.0)
    n = len(df)
    eq, pos, trades = np.empty(n), np.zeros(n), []
    for i, t in enumerate(df.index):
        e, closed, _ = step(st, t, O[i], H[i], L[i], C[i], int(S[i]), int(PV[i]), rk, fee, SLP[i], TPX[i])
        eq[i], pos[i] = e, st["dir"]
        if closed:
            trades.append(closed)
    eq = pd.Series(eq, index=df.index)
    pos = pd.Series(pos, index=df.index)
    strat = eq.pct_change().fillna(0)
    bh = (1 + df["close"].pct_change().fillna(0)).cumprod()
    cols = ["entry_time", "exit_time", "side", "entry", "exit", "pnl_%", "R"]
    tr = pd.DataFrame(trades, columns=cols + ["equity"]) if trades else pd.DataFrame(columns=cols + ["equity"])
    tr = tr[cols]
    if len(tr):
        w = tr["pnl_%"] > 0
        gp, gl = tr.loc[w, "pnl_%"].sum(), -tr.loc[~w, "pnl_%"].sum()
        pf = round(gp / gl, 2) if gl > 0 else None
        win_rate = round(w.mean() * 100, 1)
        avg_r = round(tr["R"].mean(), 2)
        avg_w = round(tr.loc[w, "pnl_%"].mean(), 2) if w.any() else 0
        avg_l = round(tr.loc[~w, "pnl_%"].mean(), 2) if (~w).any() else 0
    else:
        pf, win_rate, avg_r, avg_w, avg_l = None, 0, 0, 0, 0
    stats = {
        "Return %": round((eq.iloc[-1] - 1) * 100, 1),
        "Max DD %": round(((eq / eq.cummax() - 1).min()) * 100, 1),
        "Sharpe": round(_sharpe(strat, df), 2),
        "Trades": len(tr),
        "Win rate %": win_rate,
        "Profit factor": pf,
        "Avg R": avg_r,
        "Avg win %": avg_w,
        "Avg loss %": avg_l,
        "Open trade": "yes" if st["dir"] else "no",
    }
    return dict(stats=stats, equity=eq, bh=bh, trades=tr, pos=pos, strat=strat)


def run(df, signal, fee=0.0006, risk=None, slp=None):
    if risk is None:
        return run_simple(df, signal, fee)
    return run_sltp(df, signal, fee, risk, slp)
