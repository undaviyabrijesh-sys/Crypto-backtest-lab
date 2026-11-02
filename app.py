# Plain-English labels + help shown in the dashboard sidebar
PARAM_INFO = {
    "min_gap_pct": {"label": "Min gap size (% of price)",
                    "help": "Ignore tiny FVGs. Higher = fewer, cleaner zones. Try 0.02 to 0.08.", "step": 0.01},
    "min_impulse": {"label": "Impulse strength (x avg candle)",
                    "help": "The big middle candle of the FVG must be at least this many times the average candle size. Higher = only strong moves create zones. 0 = off.", "step": 0.1},
    "min_risk_pct": {"label": "Min stop distance (% of price)",
                     "help": "Skip trades whose stop is closer than this. Tiny stops get eaten by fees. 0 = off.", "step": 0.05},
    "trend_len": {"label": "Trend filter (EMA length)",
                  "help": "Longs only above this EMA, shorts only below. 0 = off. Try 50, 100, 200."},
    "big_mult": {"label": "Big candle = x avg candle",
                 "help": "If the confirming candle is bigger than this, wait for a pullback instead of entering at once.", "step": 0.1},
    "retrace": {"label": "Pullback needed after big candle",
                "help": "0.5 = wait for price to give back half of the big candle.", "step": 0.05},
    "retrace_wait": {"label": "Bars to wait for that pullback",
                     "help": "If no pullback within this many candles, the trade is cancelled."},
    "buffer_pct": {"label": "Stop buffer (% of price)",
                   "help": "Extra room placed beyond the touch candle for the stop.", "step": 0.01},
    "max_wait": {"label": "Bars allowed to confirm",
                 "help": "1 = the very next candle after the touch must confirm."},
    "max_zone_age": {"label": "Zone lifetime (bars)",
                     "help": "A zone is forgotten after this many candles."},
    "use_short": {"label": "Also trade shorts (1 = yes)",
                  "help": "Supply zones = mirror of demand. 0 = longs only."},
}

# Values the 'Find best settings' button is allowed to try
OPTIMIZE = {
    "min_impulse": [0, 1.0, 1.5, 2.0, 2.5],
    "min_risk_pct": [0.1, 0.15, 0.2, 0.3, 0.4],
    "trend_len": [0, 50, 100, 200],
    "min_gap_pct": [0, 0.02, 0.04, 0.08],
    "big_mult": [1.2, 1.5, 2.0, 3.0],
    "retrace": [0.382, 0.5, 0.618],
    "buffer_pct": [0.01, 0.02, 0.05],
}
