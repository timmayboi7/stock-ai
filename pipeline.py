"""
Stock Data Pipeline — TKC Studio
Phase 1: Data pull + technical signal scoring

Usage:
    python pipeline.py                    # runs default watchlist
    python pipeline.py AAPL TSLA NVDA     # custom tickers

Requirements:
    pip install yfinance ta pandas
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import ta
from datetime import datetime

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

DEFAULT_WATCHLIST = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "SPY"]

PERIOD      = "6mo"     # lookback window for indicator calculation
INTERVAL    = "1d"      # daily bars

# Signal score weights (tune these as you develop edge)
SCORE_MAP = {
    "STRONG BUY":  2,
    "BUY":         1,
    "NEUTRAL":     0,
    "SELL":        -1,
    "STRONG SELL": -2,
}


# ─────────────────────────────────────────────
# DATA LAYER
# ─────────────────────────────────────────────

def fetch_ticker(ticker: str) -> pd.DataFrame | None:
    """Pull OHLCV data from Yahoo Finance and flatten column names."""
    try:
        df = yf.download(
            ticker,
            period=PERIOD,
            interval=INTERVAL,
            progress=False,
            auto_adjust=True,
        )
        if df.empty or len(df) < 60:
            print(f"  [!] {ticker}: not enough data ({len(df)} rows)")
            return None

        # Flatten MultiIndex columns yfinance sometimes returns
        df.columns = [
            c[0].lower() if isinstance(c, tuple) else c.lower()
            for c in df.columns
        ]
        df.index.name = "date"
        return df

    except Exception as e:
        print(f"  [!] {ticker}: fetch error — {e}")
        return None


def fetch_tickers_batch(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """
    Fetch multiple tickers in a single network call — much faster than sequential.
    Returns dict of {ticker: dataframe}.
    """
    import contextlib, io
    if not tickers:
        return {}
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            if len(tickers) == 1:
                raw = yf.download(tickers[0], period=PERIOD, interval=INTERVAL,
                                  progress=False, auto_adjust=True)
                raw.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                               for c in raw.columns]
                raw.index.name = "date"
                return {tickers[0]: raw} if not raw.empty else {}
            else:
                raw = yf.download(tickers, period=PERIOD, interval=INTERVAL,
                                  progress=False, auto_adjust=True,
                                  group_by="ticker")
        result = {}
        for tkr in tickers:
            try:
                df = raw[tkr].copy().dropna()
                df.columns = [c.lower() for c in df.columns]
                df.index.name = "date"
                if not df.empty and len(df) >= 60:
                    result[tkr] = df
            except Exception:
                continue
        return result
    except Exception as e:
        print(f"  [!] Batch fetch failed: {e}")
        return {}


# ─────────────────────────────────────────────
# INDICATOR LAYER
# ─────────────────────────────────────────────

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute technical indicators and append to dataframe."""
    df = df.copy()

    # Momentum
    df["RSI_14"]         = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
    macd                 = ta.trend.MACD(df["close"], window_fast=12, window_slow=26, window_sign=9)
    df["MACD_12_26_9"]   = macd.macd()
    df["MACDh_12_26_9"]  = macd.macd_diff()
    df["MACDs_12_26_9"]  = macd.macd_signal()

    # Trend
    df["EMA_21"]         = ta.trend.EMAIndicator(df["close"], window=21).ema_indicator()
    df["EMA_50"]         = ta.trend.EMAIndicator(df["close"], window=50).ema_indicator()
    adx                  = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=14)
    df["ADX_14"]         = adx.adx()
    df["DMP_14"]         = adx.adx_pos()
    df["DMN_14"]         = adx.adx_neg()

    # Volatility / mean reversion
    bb                   = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
    df["BBU_20_2.0_2.0"] = bb.bollinger_hband()
    df["BBL_20_2.0_2.0"] = bb.bollinger_lband()
    df["BBM_20_2.0_2.0"] = bb.bollinger_mavg()
    df["BBP_20_2.0_2.0"] = bb.bollinger_pband()   # 0=at lower band, 1=at upper band
    df["ATRr_14"]        = ta.volatility.AverageTrueRange(
                               df["high"], df["low"], df["close"], window=14
                           ).average_true_range()

    # Volume
    df["OBV"]            = ta.volume.OnBalanceVolumeIndicator(
                               df["close"], df["volume"]
                           ).on_balance_volume()

    df.dropna(inplace=True)
    return df


# ─────────────────────────────────────────────
# SIGNAL LAYER
# ─────────────────────────────────────────────

def score_row(row: pd.Series) -> list[tuple]:
    """
    Score the latest bar across all indicators.
    Returns list of (indicator, signal, reason) tuples.
    """
    signals = []

    # ── RSI ──────────────────────────────────
    rsi = row.get("RSI_14", 50)
    if rsi < 30:
        signals.append(("RSI", "STRONG BUY",  f"Oversold at {rsi:.1f}"))
    elif rsi < 45:
        signals.append(("RSI", "BUY",         f"Below midline at {rsi:.1f}"))
    elif rsi > 70:
        signals.append(("RSI", "STRONG SELL", f"Overbought at {rsi:.1f}"))
    elif rsi > 55:
        signals.append(("RSI", "SELL",        f"Above midline at {rsi:.1f}"))
    else:
        signals.append(("RSI", "NEUTRAL",     f"Midrange at {rsi:.1f}"))

    # ── MACD ─────────────────────────────────
    macd_line = row.get("MACD_12_26_9", 0)
    macd_hist = row.get("MACDh_12_26_9", 0)
    if macd_hist > 0 and macd_line > 0:
        signals.append(("MACD", "STRONG BUY",  "Histogram pos + above zero"))
    elif macd_hist > 0 and macd_line < 0:
        signals.append(("MACD", "BUY",         "Histogram turning up (bullish cross)"))
    elif macd_hist < 0 and macd_line < 0:
        signals.append(("MACD", "STRONG SELL", "Histogram neg + below zero"))
    else:
        signals.append(("MACD", "SELL",        "Histogram turning down (bearish cross)"))

    # ── Bollinger Band position ───────────────
    bbp = row.get("BBP_20_2.0_2.0", 0.5)   # 0 = at lower band, 1 = at upper band
    if bbp < 0.10:
        signals.append(("BB", "STRONG BUY",  f"At/below lower band ({bbp:.2f})"))
    elif bbp < 0.25:
        signals.append(("BB", "BUY",         f"Near lower band ({bbp:.2f})"))
    elif bbp > 0.90:
        signals.append(("BB", "STRONG SELL", f"At/above upper band ({bbp:.2f})"))
    elif bbp > 0.75:
        signals.append(("BB", "SELL",        f"Near upper band ({bbp:.2f})"))
    else:
        signals.append(("BB", "NEUTRAL",     f"Mid-band at {bbp:.2f}"))

    # ── EMA trend ────────────────────────────
    ema21 = row.get("EMA_21", 0)
    ema50 = row.get("EMA_50", 0)
    separation = abs(ema21 - ema50) / ema50 * 100 if ema50 else 0
    if ema21 > ema50:
        label = "STRONG BUY" if separation > 2 else "BUY"
        signals.append(("EMA", label, f"21 EMA above 50 EMA (+{separation:.1f}%)"))
    else:
        label = "STRONG SELL" if separation > 2 else "SELL"
        signals.append(("EMA", label, f"21 EMA below 50 EMA (-{separation:.1f}%)"))

    # ── ADX (trend strength) ──────────────────
    adx = row.get("ADX_14", 20)
    dmp = row.get("DMP_14", 0)   # +DI
    dmn = row.get("DMN_14", 0)   # -DI
    if adx > 25:
        if dmp > dmn:
            signals.append(("ADX", "BUY",  f"Strong uptrend (ADX {adx:.0f})"))
        else:
            signals.append(("ADX", "SELL", f"Strong downtrend (ADX {adx:.0f})"))
    else:
        signals.append(("ADX", "NEUTRAL", f"Weak/no trend (ADX {adx:.0f})"))

    return signals


def compute_composite_score(signals: list[tuple]) -> tuple[int, int, str]:
    """
    Returns (raw_score, max_possible, grade).
    Grade: STRONG BUY / BUY / NEUTRAL / SELL / STRONG SELL
    """
    raw   = sum(SCORE_MAP.get(s[1], 0) for s in signals)
    max_s = len(signals) * 2
    pct   = raw / max_s if max_s else 0

    if pct >=  0.6:  grade = "STRONG BUY"
    elif pct >= 0.2: grade = "BUY"
    elif pct <= -0.6: grade = "STRONG SELL"
    elif pct <= -0.2: grade = "SELL"
    else:            grade = "NEUTRAL"

    return raw, max_s, grade


# ─────────────────────────────────────────────
# RISK METRICS
# ─────────────────────────────────────────────

def compute_risk(df: pd.DataFrame) -> dict:
    """ATR-based stop loss and target levels from latest close."""
    latest = df.iloc[-1]
    close  = latest["close"]
    atr    = latest.get("ATRr_14", close * 0.02)

    return {
        "close":       round(close, 2),
        "atr":         round(atr, 2),
        "stop_1x_atr": round(close - atr, 2),       # conservative stop
        "stop_2x_atr": round(close - 2 * atr, 2),   # wider stop
        "target_2r":   round(close + 2 * atr, 2),   # 2:1 reward/risk
        "target_3r":   round(close + 3 * atr, 2),   # 3:1 reward/risk
        "atr_pct":     round(atr / close * 100, 2),  # daily volatility %
    }


# ─────────────────────────────────────────────
# DISPLAY
# ─────────────────────────────────────────────

GRADE_ICON = {
    "STRONG BUY":  "▲▲",
    "BUY":         "▲ ",
    "NEUTRAL":     "── ",
    "SELL":        "▼ ",
    "STRONG SELL": "▼▼",
}

def print_ticker_report(ticker: str, result: dict):
    """Print a formatted signal report for one ticker."""
    r = result
    g = r["grade"]

    print(f"\n{'─'*58}")
    print(f"  {ticker:<8}  {GRADE_ICON.get(g,'  ')} {g:<14}  Score: {r['score']}/{r['max_score']}")
    print(f"  Close: ${r['risk']['close']:<8}  ATR: ${r['risk']['atr']} ({r['risk']['atr_pct']}%/day)")
    print(f"  Stop:  ${r['risk']['stop_2x_atr']} — ${r['risk']['stop_1x_atr']}  |  Target: ${r['risk']['target_2r']} — ${r['risk']['target_3r']}")
    print()
    for ind, sig, reason in r["signals"]:
        icon = "▲" if "BUY" in sig else ("▼" if "SELL" in sig else "─")
        print(f"    {icon} {ind:<6}  {sig:<14}  {reason}")


def print_summary_table(results: dict):
    """Print a compact ranked summary table."""
    print(f"\n{'═'*58}")
    print(f"  WATCHLIST SUMMARY  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'═'*58}")
    print(f"  {'TICKER':<8} {'GRADE':<14} {'SCORE':<10} {'CLOSE':<10} {'ATR%'}")
    print(f"  {'─'*7} {'─'*13} {'─'*9} {'─'*9} {'─'*6}")

    ranked = sorted(results.items(), key=lambda x: x[1]["score"], reverse=True)

    for ticker, r in ranked:
        icon = GRADE_ICON.get(r["grade"], "  ")
        print(
            f"  {ticker:<8} {icon} {r['grade']:<12} "
            f"{r['score']:>2}/{r['max_score']:<6} "
            f"${r['risk']['close']:<8} "
            f"{r['risk']['atr_pct']}%"
        )

    print(f"{'═'*58}")


def export_csv(results: dict, path: str = "signals.csv"):
    """Export signal summary to CSV for further analysis."""
    rows = []
    for ticker, r in results.items():
        row = {
            "ticker":  ticker,
            "date":    datetime.now().strftime("%Y-%m-%d"),
            "grade":   r["grade"],
            "score":   r["score"],
            "max":     r["max_score"],
            "close":   r["risk"]["close"],
            "atr":     r["risk"]["atr"],
            "atr_pct": r["risk"]["atr_pct"],
            "stop_1x": r["risk"]["stop_1x_atr"],
            "stop_2x": r["risk"]["stop_2x_atr"],
            "target_2r": r["risk"]["target_2r"],
            "target_3r": r["risk"]["target_3r"],
        }
        # Flatten individual indicator signals
        for ind, sig, reason in r["signals"]:
            row[f"sig_{ind.lower()}"] = sig
        rows.append(row)

    df = pd.DataFrame(rows)
    df.to_csv(path, index=False)
    print(f"\n  [✓] Exported to {path}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def run(watchlist: list[str], export: bool = True) -> dict:
    """
    Run the full pipeline for a list of tickers.
    Returns dict of results keyed by ticker.
    """
    results = {}

    print(f"\nFetching {len(watchlist)} tickers...")

    # Batch download all tickers in one network call
    print(f"  Fetching all {len(watchlist)} tickers in parallel...")
    batch = fetch_tickers_batch(watchlist)
    print(f"  Got data for {len(batch)} tickers — computing signals...")

    for ticker in watchlist:
        print(f"  → {ticker}", end="  ", flush=True)

        if ticker not in batch:
            print("skip (no data)")
            continue

        df = add_indicators(batch[ticker].copy())
        if df.empty:
            print("skip (insufficient data after indicators)")
            continue

        latest  = df.iloc[-1]
        signals = score_row(latest)
        score, max_s, grade = compute_composite_score(signals)
        risk    = compute_risk(df)

        results[ticker] = {
            "grade":     grade,
            "score":     score,
            "max_score": max_s,
            "signals":   signals,
            "risk":      risk,
            "df":        df,
        }
        print(f"{GRADE_ICON.get(grade,'')} {grade}")

    # Reports
    print_summary_table(results)

    for ticker, r in sorted(results.items(), key=lambda x: x[1]["score"], reverse=True):
        print_ticker_report(ticker, r)

    if export:
        export_csv(results)

    return results


if __name__ == "__main__":
    watchlist = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_WATCHLIST
    watchlist = [t.upper() for t in watchlist]
    run(watchlist)
