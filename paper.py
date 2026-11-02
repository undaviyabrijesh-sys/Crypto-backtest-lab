import json, pathlib, ccxt, pandas as pd
from engine import step, new_state, DEFAULT_RISK

P = pathlib.Path("paper"); P.mkdir(exist_ok=True)
cfg = json.loads((P / "config.json").read_text())
rk = {**DEFAULT_RISK, **cfg.get("risk", {})}
fee = cfg["fee"]
ns = {}
exec(pathlib.Path(cfg["strategy"]).read_text(), ns)

ex = getattr(ccxt, cfg["exchange"])()
rows = ex.fetch_ohlcv(cfg["symbol"], cfg["tf"], limit=1000)
df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
df["time"] = pd.to_datetime(df["time"], unit="ms")
df = df.set_index("time").iloc[:-1]          # drop the still-forming candle
sig = pd.Series(ns["signals"](df, cfg["params"]), index=df.index).fillna(0).clip(-1, 1)
prev = sig.shift(1).fillna(0)
rk = {**DEFAULT_RISK, **ns.get("RISK", {}), **cfg.get("risk", {})}
slp = (pd.Series(ns["stops"](df, cfg["params"]), index=df.index).fillna(0)
       if "stops" in ns else None)

sf = P / "state.json"
eq_rows, tr_rows = [], []
if sf.exists():
    S = json.loads(sf.read_text())
else:                                          # first run: start live from now
    S = dict(last=str(df.index[-1]), equity=cfg["start_equity"],
             st=new_state(cfg["start_equity"]))
    eq_rows.append(dict(time=df.index[-1], equity=S["equity"], pos=0,
                        close=float(df["close"].iloc[-1])))

for t in df.index[df.index > pd.Timestamp(S["last"])]:
    r = df.loc[t]
    e, closed, _ = step(S["st"], t, float(r["open"]), float(r["high"]), float(r["low"]),
                        float(r["close"]), int(sig[t]), int(prev[t]), rk, fee,
                        float(slp[t]) if slp is not None else 0.0)
    S["equity"] = e
    if closed:
        tr_rows.append(closed)
    eq_rows.append(dict(time=t, equity=e, pos=S["st"]["dir"], close=float(r["close"])))

S["last"] = str(df.index[-1])
sf.write_text(json.dumps(S))
for name, r in (("equity", eq_rows), ("trades", tr_rows)):
    if r:
        f = P / f"{name}.csv"
        pd.DataFrame(r).to_csv(f, mode="a", header=not f.exists(), index=False)
