import calendar, glob, json, pathlib, random
import numpy as np, pandas as pd, streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from engine import run

st.set_page_config(page_title="Backtest Lab", page_icon="📈", layout="wide")
st.markdown("""<style>
div[data-testid="stMetric"]{background:#131a2b;border:1px solid #232c45;
border-radius:14px;padding:14px 16px}
div[data-testid="stMetricValue"]{font-size:1.5rem}
.block-container{padding-top:1.5rem}
</style>""", unsafe_allow_html=True)

G, R, GREY = "#00d09c", "#ff5c7a", "#6b7694"
RISK_KEYS = {"sl": "risk_sl", "tp1_r": "risk_tp1", "tp2_r": "risk_tp2", "lot1_pct": "risk_lot1"}
NICE = {"tp1_r": "TP1", "tp2_r": "TP2", "lot1_pct": "Lot1 %", "sl": "SL"}


def style(fig, h=420):
    fig.update_layout(template="plotly_dark", height=h, hovermode="x unified",
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=10, r=10, t=30, b=10),
                      legend=dict(orientation="h", y=1.1))
    fig.update_xaxes(gridcolor="#1c2540")
    fig.update_yaxes(gridcolor="#1c2540")
    return fig


def show_metrics(stats):
    items = list(stats.items())
    for i in range(0, len(items), 5):
        for c, (k, v) in zip(st.columns(5), items[i:i + 5]):
            c.metric(k, "—" if v is None else v)


def verdict(s):
    n, pf, dd, ret = s["Trades"], s.get("Profit factor"), s["Max DD %"], s["Return %"]
    if n < 30:
        st.warning(f"Only {n} trades: too few to trust. Use a longer date range or a looser filter.")
    elif pf is not None and pf < 1:
        st.error(f"Losing setup: profit factor {pf} (below 1 means losses outweigh wins). "
                 "Open the 🔬 Optimizer tab and tap **Find best settings**.")
    elif abs(dd) > 40:
        st.warning(f"Profitable ({ret}%) but drawdown {dd}% is too deep to trade comfortably.")
    elif ret > 0:
        st.success(f"Looks healthy: {n} trades, profit factor {pf}, drawdown {dd}%. "
                   "Now confirm it on other datasets before trusting it.")


st.title("📈 Backtest Lab")

files = sorted(glob.glob("data/*.csv"))
if not files:
    st.warning("No data yet. Run the update-data workflow in GitHub Actions first.")
    st.stop()

sb = st.sidebar
sb.title("⚙️ Settings")
f = sb.selectbox("Market & timeframe", files, help="Candle file to test on, e.g. BTCUSDT_15m.")
fee = sb.number_input("Fee per side %", 0.0, 1.0, 0.06, 0.01,
                      help="Exchange fee for each buy or sell. Set 0 to see the strategy's raw edge.") / 100
df = pd.read_csv(f, parse_dates=["time"]).set_index("time")
r = sb.date_input("Date range", [df.index[0].date(), df.index[-1].date()])
if len(r) < 2:
    st.info("Pick both a start and an end date in the sidebar (tap the › arrow at top left).")
    st.stop()
df = df.loc[str(r[0]):str(r[1])]
if df.empty:
    st.error("No candles in that date range. Pick dates inside the data.")
    st.stop()

sb.subheader("Strategy")
up = sb.file_uploader("Upload your own .py strategy", type="py")
if up:
    src, sname = up.read().decode(), "upload:" + up.name
else:
    sname = sb.selectbox("Saved strategy", sorted(glob.glob("strategies/*.py")))
    src = pathlib.Path(sname).read_text()
ns = {}
exec(src, ns)

info = ns.get("PARAM_INFO", {})
params = {}
with sb.expander("Entry rules", expanded=True):
    for k, v in ns.get("PARAMS", {}).items():
        m = info.get(k, {})
        kw = dict(help=m.get("help"), key=f"{sname}|{k}")
        label = m.get("label", k)
        if isinstance(v, int) and not isinstance(v, bool):
            params[k] = st.number_input(label, value=v, step=1, **kw)
        else:
            params[k] = st.number_input(label, value=float(v), step=m.get("step", 0.01), format="%.4f", **kw)

sb.subheader("Risk & targets")
engine_mode = sb.radio("Engine", ["SL / TP (2 lots)", "Signal only"],
                       help="SL/TP: trades exit at stop, targets, or your rules. Signal only: just follows the signal.")
risk = None
if engine_mode.startswith("SL"):
    unit = sb.radio("Stop-loss unit", ["points", "%"], index=1, horizontal=True)
    risk = dict(
        sl_mode=unit,
        sl=sb.number_input("Stop loss", min_value=0.0001, value=0.5, format="%.4f", key="risk_sl",
                           help="Fixed stop. Ignored if the strategy sets its own stop (e.g. touch candle)."),
        tp1_r=sb.number_input("Target 1 (x stop distance)", min_value=0.1, max_value=50.0, value=1.0,
                              step=0.1, key="risk_tp1", help="1 = profit equal to the risk. Lot 1 exits here."),
        tp2_r=sb.number_input("Target 2 (x stop distance)", min_value=0.1, max_value=50.0, value=2.0,
                              step=0.1, key="risk_tp2", help="Lot 2 exits here (2 = reward is twice the risk)."),
        lot1_pct=sb.slider("Lot 1 share %", 10, 100, 50, 5, key="risk_lot1",
                           help="Share of the position that books profit at Target 1."),
        tsl=sb.checkbox("After Target 1, move lot 2 stop to cost", True,
                        help="Protects the rest of the trade once the first target is hit."),
        exit_on_signal=sb.checkbox("Exit when the signal reverses",
                                   ns.get("RISK", {}).get("exit_on_signal", True), key=f"{sname}|exit"),
    )
    if "stops" in ns:
        sb.caption("This strategy sets its own stop (touch candle), so the Stop loss box is ignored.")

sig = ns["signals"](df, params)
slp = ns["stops"](df, params) if "stops" in ns else None
res = run(df, sig, fee, risk, slp)

t1, t2, t3 = st.tabs(["📊 Backtest", "🔬 Optimizer", "🧪 Paper trading"])

with t1:
    show_metrics(res["stats"])
    verdict(res["stats"])

    eq, bh = res["equity"], res["bh"]
    dd = (eq / eq.cummax() - 1) * 100
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.72, 0.28], vertical_spacing=0.04)
    fig.add_scatter(x=eq.index, y=eq, name="Strategy", line=dict(color=G, width=2), row=1, col=1)
    fig.add_scatter(x=bh.index, y=bh, name="Buy & hold", line=dict(color=GREY, width=1.5), row=1, col=1)
    fig.add_scatter(x=dd.index, y=dd, name="Drawdown %", fill="tozeroy",
                    line=dict(color=R, width=1), row=2, col=1)
    st.plotly_chart(style(fig, 520), width="stretch")

    st.subheader("Price & entries")
    n = st.slider("Bars shown", 50, max(51, min(len(df), 3000)), min(500, len(df)))
    d = df.tail(n)
    pp = res["pos"].reindex(d.index)
    ch = pp.diff().fillna(0) != 0
    lg, sh = d[(pp == 1) & ch], d[(pp == -1) & ch]
    pf = go.Figure(go.Candlestick(x=d.index, open=d.open, high=d.high, low=d.low, close=d.close,
                                  increasing_line_color=G, decreasing_line_color=R, name="Price"))
    pf.add_scatter(x=lg.index, y=lg.close, mode="markers", name="Long entry",
                   marker=dict(symbol="triangle-up", size=11, color=G, line=dict(width=1, color="white")))
    pf.add_scatter(x=sh.index, y=sh.close, mode="markers", name="Short entry",
                   marker=dict(symbol="triangle-down", size=11, color=R, line=dict(width=1, color="white")))
    pf.update_layout(xaxis_rangeslider_visible=False)
    st.plotly_chart(style(pf, 460), width="stretch")

    st.subheader("Monthly returns %")
    m = ((1 + res["strat"]).resample("ME").prod() - 1) * 100
    hm = pd.DataFrame({"y": m.index.year, "m": m.index.month, "v": m.values}) \
           .pivot(index="y", columns="m", values="v")
    hf = go.Figure(go.Heatmap(
        z=hm.values, x=[calendar.month_abbr[i] for i in hm.columns], y=hm.index.astype(str),
        colorscale=[[0, R], [0.5, "#131a2b"], [1, G]], zmid=0,
        text=np.round(hm.values, 1), texttemplate="%{text}", showscale=False))
    hf.update_yaxes(type="category")
    st.plotly_chart(style(hf, 260), width="stretch")

    a, b = st.columns(2)
    a.subheader("Trade PnL distribution")
    hist = go.Figure(go.Histogram(x=res["trades"]["pnl_%"], marker_color=G, nbinsx=30))
    a.plotly_chart(style(hist, 300), width="stretch")
    b.subheader("Last trades")
    b.dataframe(res["trades"].tail(50).iloc[::-1], width="stretch", height=300)
    st.download_button("⬇️ Download all trades (CSV)", res["trades"].to_csv(index=False),
                       "trades.csv", "text/csv")

    with st.expander("📋 Copy these settings into paper trading (paper/config.json)"):
        st.code(json.dumps({
            "strategy": sname, "params": params, "fee": fee,
            "risk": {k: v for k, v in (risk or {}).items()}}, indent=2), language="json")


def apply_settings(sname_, sp, rs):
    for k, v in sp.items():
        st.session_state[f"{sname_}|{k}"] = v
    for k, v in rs.items():
        st.session_state[RISK_KEYS[k]] = v
    st.session_state["applied"] = True


def label_settings(sp, rs):
    parts = [f"{k}={v}" for k, v in sp.items()] + [f"{NICE.get(k, k)}={v}" for k, v in rs.items()]
    return ", ".join(parts) if parts else "(your current settings)"


with t2:
    if risk is None:
        st.info("Set Engine to **SL / TP (2 lots)** in the sidebar to use the optimizer.")
    else:
        if st.session_state.pop("applied", False):
            st.success("Settings applied. Open the 📊 Backtest tab to see the full result.")
        st.subheader("🤖 Find best settings")
        st.caption("Tries many combinations on the first part of your data, then re-tests the best ones "
                   "on the last part, which they have never seen. Only trust settings that still win there.")
        g1, g2, g3 = st.columns(3)
        goal = g1.selectbox("Goal", ["Balanced (return vs drawdown)", "Highest return",
                                     "Best profit factor", "Best Sharpe"])
        dd_cap = g2.slider("Max drawdown allowed %", 10, 90, 40, 5)
        min_tr = g3.number_input("Minimum trades", 10, 1000, 30, 10)
        trials = g1.slider("Combinations to try", 20, 200, 60, 10)
        hold = g2.slider("Keep last % of data for testing", 20, 50, 30, 5)
        tune_risk = g3.checkbox("Also tune targets & lot split", True)

        if st.button("🚀 Find best settings", type="primary"):
            P0 = ns.get("PARAMS", {})
            space = {k: v for k, v in ns.get("OPTIMIZE", {}).items() if k in P0}
            rspace = {}
            if tune_risk:
                rspace = {"tp1_r": [0.5, 1.0, 1.5], "tp2_r": [1.5, 2.0, 3.0, 4.0], "lot1_pct": [30, 50, 70]}
                if slp is None:
                    rspace["sl"] = [round(risk["sl"] * x, 4) for x in (0.5, 0.75, 1.0, 1.5, 2.0)]
            cut = int(len(df) * (1 - hold / 100))
            dtr, dte = df.iloc[:cut], df.iloc[cut:]
            cache = {}

            def sigs(sp):
                key = tuple(sorted(sp.items()))
                if key not in cache:
                    pt = {**params, **sp}
                    cache[key] = (ns["signals"](df, pt), ns["stops"](df, pt) if "stops" in ns else None)
                return cache[key]

            def seg(dx, sp, rs):
                sg, st_ = sigs(sp)
                return run(dx, sg.reindex(dx.index), fee, {**risk, **rs},
                           None if st_ is None else st_.reindex(dx.index))["stats"]

            def score(s):
                ret, ddv, pfv, shp, trd = (s["Return %"], s["Max DD %"], s.get("Profit factor") or 0,
                                           s["Sharpe"], s["Trades"])
                if trd < min_tr:
                    return -1e9 + trd
                if abs(ddv) > dd_cap:
                    return -1e8 + ret
                return {"Highest return": ret, "Best profit factor": pfv, "Best Sharpe": shp}.get(
                    goal, ret / max(abs(ddv), 5))

            rng, seen, rows = random.Random(42), set(), []
            todo = [({}, {})]                     # trial 0 = your current settings
            tries = 0
            while len(todo) < trials and tries < trials * 20:
                tries += 1
                sp = {k: (int(rng.choice(v)) if isinstance(P0[k], int) else float(rng.choice(v)))
                      for k, v in space.items()}
                rs = {k: (int(rng.choice(v)) if k == "lot1_pct" else float(rng.choice(v)))
                      for k, v in rspace.items()}
                if rs.get("tp2_r", risk["tp2_r"]) < rs.get("tp1_r", risk["tp1_r"]):
                    continue
                sig_key = (tuple(sorted(sp.items())), tuple(sorted(rs.items())))
                if sig_key not in seen:
                    seen.add(sig_key)
                    todo.append((sp, rs))
            bar = st.progress(0.0, text="Trying combinations...")
            for i, (sp, rs) in enumerate(todo):
                s = seg(dtr, sp, rs)
                rows.append(dict(sp=sp, rs=rs, train=s, score=score(s)))
                bar.progress((i + 1) / len(todo))
            base = rows[0]
            top = sorted(rows[1:], key=lambda x: -x["score"])[:5]
            out = []
            for rank, row in zip(["Current"] + list(range(1, len(top) + 1)), [base] + top):
                te = seg(dte, row["sp"], row["rs"])
                ok = (te["Trades"] >= max(5, min_tr // 3) and te["Return %"] > 0 and
                      (te.get("Profit factor") or 0) > 1 and abs(te["Max DD %"]) <= dd_cap)
                out.append(dict(rank=rank, sp=row["sp"], rs=row["rs"], tr=row["train"], te=te, ok=ok,
                                valid=row["score"] > -1e8))
            bar.empty()
            st.session_state["auto"] = dict(ctx=(sname, f), rows=out, cut=dtr.index[-1], n=len(todo))

        A = st.session_state.get("auto")
        if A and A["ctx"] == (sname, f):
            rows = A["rows"]
            st.caption(f"Tried {A['n']} combinations. Training data ends {A['cut']:%Y-%m-%d}; "
                       "everything after that is unseen test data.")
            good = [x for x in rows[1:] if x["ok"] and x["valid"]]
            if good:
                st.success(f"Best setting that also won on unseen data: #{good[0]['rank']}. "
                           "Apply it, then check it on other markets and timeframes.")
            else:
                st.warning("No setting beat your limits AND stayed profitable on unseen data. That usually means "
                           "there is no stable edge here (or it only worked by luck). Do not trade these. "
                           "Try another timeframe/market, relax the limits, or change the strategy rules.")
            table = pd.DataFrame([{
                "#": str(x["rank"]), "Settings": label_settings(x["sp"], x["rs"]),
                "Train return %": x["tr"]["Return %"], "Train DD %": x["tr"]["Max DD %"],
                "Train trades": x["tr"]["Trades"], "Train PF": x["tr"].get("Profit factor"),
                "Test return %": x["te"]["Return %"], "Test DD %": x["te"]["Max DD %"],
                "Test trades": x["te"]["Trades"], "Test PF": x["te"].get("Profit factor"),
                "Holds up?": "✅" if x["ok"] and x["valid"] else "❌"} for x in rows])
            st.dataframe(table, hide_index=True, width="stretch")
            cols = st.columns(len(rows) - 1) if len(rows) > 1 else []
            for c, x in zip(cols, rows[1:]):
                c.button(f"Apply #{x['rank']}", key=f"apply{x['rank']}", on_click=apply_settings,
                         args=(sname, x["sp"], x["rs"]))

        with st.expander("Manual 2-setting heatmap"):
            use_sl = slp is None
            st.caption(("Sweeps stop loss vs Target 2" if use_sl else "Sweeps Target 1 vs Target 2")
                       + " with everything else as in the sidebar. Look for a broad green area, "
                       "not one hot cell.")
            c1, c2, c3 = st.columns(3)
            rname = "SL" if use_sl else "Target 1 (x stop)"
            r0 = float(risk["sl"]) if use_sl else float(risk["tp1_r"])
            sl_lo = c1.number_input(f"{rname} from", min_value=0.0001, value=r0 * 0.5, format="%.4f")
            sl_hi = c1.number_input(f"{rname} to", min_value=0.0001, value=r0 * 2.0, format="%.4f")
            tp_lo = c2.number_input("Target 2 (x stop) from", min_value=0.1, value=1.0, step=0.5)
            tp_hi = c2.number_input("Target 2 (x stop) to", min_value=0.1, value=4.0, step=0.5)
            n_steps = c3.slider("Grid size", 3, 8, 5)
            metric = c3.selectbox("Metric", ["Return %", "Sharpe", "Profit factor", "Max DD %", "Win rate %", "Avg R"])
            if st.button("Run sweep"):
                sls, tps = np.linspace(sl_lo, sl_hi, n_steps), np.linspace(tp_lo, tp_hi, n_steps)
                Z = np.full((n_steps, n_steps), np.nan)
                bar = st.progress(0.0)
                for i, s in enumerate(sls):
                    for j, tv in enumerate(tps):
                        rr = run(df, sig, fee, {**risk, ("sl" if use_sl else "tp1_r"): float(s),
                                                "tp2_r": float(tv)}, slp)
                        v = rr["stats"][metric]
                        Z[i, j] = np.nan if v is None else v
                    bar.progress((i + 1) / n_steps)
                bar.empty()
                st.session_state["sweep"] = (sls, tps, Z, metric, rname)
            if "sweep" in st.session_state and st.session_state["sweep"][4] == rname:
                sls, tps, Z, mname, _ = st.session_state["sweep"]
                if np.isnan(Z).all():
                    st.warning("No valid results (no trades). Widen the date range or the range above.")
                else:
                    bi, bj = np.unravel_index(np.nanargmax(Z), Z.shape)
                    st.success(f"Best {mname}: **{Z[bi, bj]:.2f}** at {rname} {sls[bi]:.4f}, "
                               f"Target 2 {tps[bj]:.1f}R")
                    hf = go.Figure(go.Heatmap(
                        z=Z, x=[f"{t:.1f}R" for t in tps], y=[f"{s:.4f}" for s in sls],
                        colorscale=[[0, R], [0.5, "#131a2b"], [1, G]],
                        text=np.round(Z, 2), texttemplate="%{text}", showscale=False))
                    hf.update_xaxes(title="Target 2 (x stop)")
                    hf.update_yaxes(title=rname, type="category")
                    st.plotly_chart(style(hf, 420), width="stretch")

with t3:
    pdir = pathlib.Path("paper")
    if not (pdir / "equity.csv").exists():
        st.info("No paper data yet. Run the paper-trade workflow once from the Actions tab.")
    else:
        S = json.loads((pdir / "state.json").read_text())
        cfg = json.loads((pdir / "config.json").read_text())
        pst = S["st"]
        pe = pd.read_csv(pdir / "equity.csv", parse_dates=["time"])
        start = cfg["start_equity"]
        c = st.columns(4)
        c[0].metric("Equity", f"{S['equity']:,.0f}", f"{(S['equity'] / start - 1) * 100:.2f}%")
        c[1].metric("Position", {1: "🟢 LONG", -1: "🔴 SHORT", 0: "⚪ FLAT"}[pst["dir"]])
        c[2].metric("Market", f"{cfg['symbol']} {cfg['tf']}")
        c[3].metric("Last bar", S["last"][5:16])
        if pst["dir"]:
            o = st.columns(4)
            o[0].metric("Entry", f"{pst['entry']:,.2f}")
            o[1].metric("Stop loss", f"{(pst['sl2'] if pst['w2'] else pst['sl1']):,.2f}",
                        "at cost" if pst["moved"] else None)
            o[2].metric("TP1", f"{pst['tp1']:,.2f}" if pst["w1"] else "hit ✅")
            o[3].metric("TP2", f"{pst['tp2']:,.2f}" if pst["w2"] else "—")

        pfig = go.Figure(go.Scatter(x=pe.time, y=pe.equity, name="Paper equity",
                                    line=dict(color=G, width=2)))
        tp = pdir / "trades.csv"
        if tp.exists():
            pt = pd.read_csv(tp, parse_dates=["exit_time"])
            pfig.add_scatter(x=pt.exit_time, y=pt.equity, mode="markers", name="Closed trades",
                             marker=dict(size=8, color="white"))
            st.plotly_chart(style(pfig, 420), width="stretch")
            st.dataframe(pt.tail(50).iloc[::-1], width="stretch")
        else:
            st.plotly_chart(style(pfig, 420), width="stretch")
