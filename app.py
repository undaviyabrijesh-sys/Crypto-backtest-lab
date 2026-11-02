import calendar, glob, json, pathlib
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


files = sorted(glob.glob("data/*.csv"))
if not files:
    st.warning("No data yet. Run the update-data workflow first.")
    st.stop()

sb = st.sidebar
sb.title("⚙️ Settings")
f = sb.selectbox("Dataset", files)
fee = sb.number_input("Fee per side %", 0.0, 1.0, 0.06, 0.01) / 100
df = pd.read_csv(f, parse_dates=["time"]).set_index("time")
r = sb.date_input("Range", [df.index[0].date(), df.index[-1].date()])
if len(r) < 2:
    st.stop()
df = df.loc[str(r[0]):str(r[1])]

sb.subheader("Strategy")
up = sb.file_uploader("Upload .py", type="py")
if up:
    src = up.read().decode()
else:
    src = pathlib.Path(sb.selectbox("Saved", sorted(glob.glob("strategies/*.py")))).read_text()
ns = {}
exec(src, ns)
params = {}
for k, v in ns.get("PARAMS", {}).items():
    if isinstance(v, int):
        params[k] = sb.number_input(k, value=v, step=1)
    else:
        params[k] = sb.number_input(k, value=float(v), format="%.4f")

sb.subheader("Risk")
engine_mode = sb.radio("Engine", ["SL / TP (2 lots)", "Signal only"])
risk = None
if engine_mode.startswith("SL"):
    unit = sb.radio("SL unit", ["points", "%"], index=1, horizontal=True)
    risk = dict(
        sl_mode=unit,
        sl=sb.number_input("Stop loss", min_value=0.0001, value=0.5, format="%.4f"),
        tp1_r=sb.number_input("TP1 (x SL) - lot 1", min_value=0.1, max_value=50.0, value=1.0, step=0.1),
        tp2_r=sb.number_input("TP2 (x SL) - lot 2", min_value=0.1, max_value=50.0, value=2.0, step=0.1),
        lot1_pct=sb.slider("Lot 1 share %", 10, 100, 50, 5),
        tsl=sb.checkbox("Lot 2 SL moves to cost when TP1 hits", True),
        exit_on_signal=sb.checkbox("Exit on opposite signal",
                                   ns.get("RISK", {}).get("exit_on_signal", True)),
    )
    if "stops" in ns:
        sb.caption("Stop loss comes from the strategy (e.g. touch candle), so the SL input above is ignored. "
                   "TP1/TP2 are multiples of that stop distance.")

sig = ns["signals"](df, params)
slp = ns["stops"](df, params) if "stops" in ns else None
res = run(df, sig, fee, risk, slp)

st.title("📈 Backtest Lab")
t1, t2, t3 = st.tabs(["📊 Backtest", "🔬 Optimizer", "🧪 Paper trading"])

with t1:
    show_metrics(res["stats"])

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

with t2:
    if risk is None:
        st.info("Set Engine to **SL / TP (2 lots)** in the sidebar to optimise SL and TP.")
    else:
        use_sl = slp is None
        st.caption(("Sweeps stop loss vs TP2" if use_sl else "Sweeps TP1 vs TP2 (the stop comes from the strategy)")
                   + " with every other setting as in the sidebar. "
                   "Look for a broad green plateau, not a single hot cell: that is usually curve fitting.")
        c1, c2, c3 = st.columns(3)
        rname = "SL" if use_sl else "TP1 (x SL)"
        r0 = float(risk["sl"]) if use_sl else float(risk["tp1_r"])
        sl_lo = c1.number_input(f"{rname} from", min_value=0.0001, value=r0 * 0.5, format="%.4f")
        sl_hi = c1.number_input(f"{rname} to", min_value=0.0001, value=r0 * 2.0, format="%.4f")
        tp_lo = c2.number_input("TP2 (x SL) from", min_value=0.1, value=1.0, step=0.5)
        tp_hi = c2.number_input("TP2 (x SL) to", min_value=0.1, value=4.0, step=0.5)
        n_steps = c3.slider("Grid size", 3, 8, 5)
        metric = c3.selectbox("Metric", ["Return %", "Sharpe", "Profit factor", "Max DD %", "Win rate %", "Avg R"])
        if st.button("Run sweep", type="primary"):
            sls, tps = np.linspace(sl_lo, sl_hi, n_steps), np.linspace(tp_lo, tp_hi, n_steps)
            Z = np.full((n_steps, n_steps), np.nan)
            bar = st.progress(0.0)
            for i, s in enumerate(sls):
                for j, tv in enumerate(tps):
                    rr = run(df, sig, fee,
                             {**risk, ("sl" if use_sl else "tp1_r"): float(s), "tp2_r": float(tv)}, slp)
                    v = rr["stats"][metric]
                    Z[i, j] = np.nan if v is None else v
                bar.progress((i + 1) / n_steps)
            bar.empty()
            st.session_state["sweep"] = (sls, tps, Z, metric, rname)
        if "sweep" in st.session_state and st.session_state["sweep"][4] == rname:
            sls, tps, Z, mname, _ = st.session_state["sweep"]
            if np.isnan(Z).all():
                st.warning("No valid results (no trades). Widen the date range or the SL range.")
            else:
                bi, bj = np.unravel_index(np.nanargmax(Z), Z.shape)
                st.success(f"Best {mname}: **{Z[bi, bj]:.2f}** at {rname} {sls[bi]:.4f}"
                           f"{' ' + risk['sl_mode'] if use_sl else ''}, TP2 {tps[bj]:.1f}R")
                hf = go.Figure(go.Heatmap(
                    z=Z, x=[f"{t:.1f}R" for t in tps], y=[f"{s:.4f}" for s in sls],
                    colorscale=[[0, R], [0.5, "#131a2b"], [1, G]],
                    text=np.round(Z, 2), texttemplate="%{text}", showscale=False))
                hf.update_xaxes(title="TP2 (x SL)")
                hf.update_yaxes(title=f"SL ({risk['sl_mode']})" if use_sl else "TP1 (x SL)", type="category")
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
