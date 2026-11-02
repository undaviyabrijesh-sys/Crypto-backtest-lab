import ccxt, pandas as pd, pathlib, time

EXCHANGE = "binanceus"   # change if a pair is missing
PAIRS = ["BTC/USDT", "ETH/USDT"]
TFS = ["15m", "1h"]
DAYS = 365


def fetch(symbol, tf):
    ex = getattr(ccxt, EXCHANGE)()
    since = ex.milliseconds() - DAYS * 86400000
    rows = []
    while since < ex.milliseconds():
        b = ex.fetch_ohlcv(symbol, tf, since=since, limit=1000)
        if not b:
            break
        rows += b
        since = b[-1][0] + 1
        time.sleep(ex.rateLimit / 1000)
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("time")
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    pathlib.Path("data").mkdir(exist_ok=True)
    df.to_csv(f"data/{symbol.replace('/', '')}_{tf}.csv", index=False)


if __name__ == "__main__":
    for s in PAIRS:
        for t in TFS:
            fetch(s, t)
