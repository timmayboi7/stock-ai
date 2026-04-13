"""
Crypto Trader — TKC Studio
Signals + Alpaca paper trading for cryptocurrency.

Key differences from stocks:
  - Trades 24/7, no market hours
  - Uses notional (dollar amount) sizing instead of share qty
  - No bracket orders — stop loss placed as separate order
  - Much higher volatility — position sizes are smaller
  - yfinance symbol: BTC-USD  |  Alpaca symbol: BTC/USD

Usage:
    python crypto_trader.py              # single cycle
    python crypto_trader.py --status     # portfolio only
    python crypto_trader.py --dry-run    # simulate

Called from dashboard.py for the Crypto tab.
"""

import os
import sys
import csv
import time
import warnings
import contextlib
import io
warnings.filterwarnings("ignore")

from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

import yfinance as yf
import pandas as pd
import ta

load_dotenv()

try:
    from github_logger import log_cycle, log_error
    _LOGGER_AVAILABLE = True
except ImportError:
    _LOGGER_AVAILABLE = False


def load_watchlist_from_config(key: str, fallback: list) -> list:
    """Load watchlist from config.json, fall back to default if not found."""
    from pathlib import Path
    import json
    config_path = Path(os.path.dirname(os.path.abspath(__file__))) / "config.json"
    try:
        if config_path.exists():
            data = json.loads(config_path.read_text(encoding="utf-8"))
            wl = data.get(key, [])
            if wl:
                return wl
    except Exception:
        pass
    return fallback


# ─────────────────────────────────────────────
# CRYPTO UNIVERSE
# ─────────────────────────────────────────────

# yfinance format → Alpaca format
CRYPTO_UNIVERSE = {
    "BTC-USD":  "BTC/USD",
    "ETH-USD":  "ETH/USD",
    "SOL-USD":  "SOL/USD",
    "BNB-USD":  "BNB/USD",
    "XRP-USD":  "XRP/USD",
    "ADA-USD":  "ADA/USD",
    "AVAX-USD": "AVAX/USD",
    "DOGE-USD": "DOGE/USD",
    "DOT-USD":  "DOT/USD",
    "LINK-USD": "LINK/USD",
    "ATOM-USD": "ATOM/USD",
    "LTC-USD":  "LTC/USD",
    "BCH-USD":  "BCH/USD",
    "ALGO-USD": "ALGO/USD",
    "XLM-USD":  "XLM/USD",
    "NEAR-USD": "NEAR/USD",
    "FIL-USD":  "FIL/USD",
    "ICP-USD":  "ICP/USD",
}

# Default watchlist (subset of universe)
DEFAULT_CRYPTO_WATCHLIST = [
    "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD",
    "XRP-USD", "ADA-USD", "AVAX-USD", "DOGE-USD",
]

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

# Position sizing — crypto is volatile, use smaller sizes
MAX_POSITION_PCT   = 0.03    # max 3% of portfolio per trade
MAX_OPEN_POSITIONS = 5       # max simultaneous crypto positions
ENTRY_SCORE_MIN    = 3       # lower threshold than stocks (crypto oversells hard)
EXIT_SCORE_MAX     = -2      # exit if score drops here

STOP_ATR_MULT      = 2.5     # wider stops for crypto volatility
TARGET_ATR_MULT    = 4.0     # bigger targets to justify the risk

TRADE_LOG_PATH     = "crypto_trades.csv"


# ─────────────────────────────────────────────
# SIGNAL ENGINE
# ─────────────────────────────────────────────

def score_crypto(yf_symbol: str) -> dict | None:
    """Fetch data and compute signal score for one crypto."""
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            df = yf.download(yf_symbol, period="6mo", interval="1d",
                             progress=False, auto_adjust=True)
        if df.empty or len(df) < 50:
            return None

        df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                      for c in df.columns]

        df["rsi"]   = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
        bb          = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
        df["bbp"]   = bb.bollinger_pband()
        df["ema21"] = ta.trend.EMAIndicator(df["close"], window=21).ema_indicator()
        df["ema50"] = ta.trend.EMAIndicator(df["close"], window=50).ema_indicator()
        macd        = ta.trend.MACD(df["close"])
        df["macdh"] = macd.macd_diff()
        df["atr"]   = ta.volatility.AverageTrueRange(
                          df["high"], df["low"], df["close"], window=14
                      ).average_true_range()
        df.dropna(inplace=True)
        if df.empty:
            return None

        row     = df.iloc[-1]
        close   = float(row["close"])
        rsi     = float(row["rsi"])
        bbp     = float(row["bbp"])
        ema21   = float(row["ema21"])
        ema50   = float(row["ema50"])
        macdh   = float(row["macdh"])
        atr     = float(row["atr"])
        atr_pct = atr / close * 100

        score = 0
        if rsi < 30:      score += 2
        elif rsi < 45:    score += 1
        elif rsi > 70:    score -= 2
        elif rsi > 55:    score -= 1
        if bbp < 0.10:    score += 2
        elif bbp < 0.25:  score += 1
        elif bbp > 0.90:  score -= 2
        elif bbp > 0.75:  score -= 1
        if ema21 > ema50: score += 1
        else:             score -= 1
        if macdh > 0:     score += 1
        else:             score -= 1

        tags = []
        if score >= 4:                     tags.append("Strong Signal")
        if rsi < 35 and bbp < 0.20:       tags.append("Oversold Bounce")
        if ema21 > ema50 and macdh > 0:   tags.append("Momentum")
        if not tags and score >= 2:        tags.append("Watch")

        alpaca_sym = CRYPTO_UNIVERSE.get(yf_symbol, yf_symbol.replace("-USD", "/USD"))
        name       = yf_symbol.replace("-USD", "")

        return {
            "yf_symbol":    yf_symbol,
            "alpaca":       alpaca_sym,
            "name":         name,
            "score":        score,
            "close":        round(close, 6),
            "rsi":          round(rsi, 1),
            "bbp":          round(bbp, 3),
            "atr_pct":      round(atr_pct, 2),
            "atr":          round(atr, 6),
            "uptrend":      ema21 > ema50,
            "stop":         round(close - atr * STOP_ATR_MULT, 6),
            "target":       round(close + atr * TARGET_ATR_MULT, 6),
            "tags":         tags,
            "df":           df,
        }
    except Exception:
        return None


def scan_watchlist(watchlist: list[str]) -> list[dict]:
    """Score all cryptos in watchlist, return sorted by score."""
    results = []
    for sym in watchlist:
        r = score_crypto(sym)
        if r:
            results.append(r)
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


# ─────────────────────────────────────────────
# ALPACA CLIENT
# ─────────────────────────────────────────────

def get_client():
    from alpaca.trading.client import TradingClient
    key    = os.environ.get("ALPACA_API_KEY")
    secret = os.environ.get("ALPACA_SECRET_KEY")
    if not key or not secret:
        print("[!] Missing Alpaca keys in .env")
        sys.exit(1)
    return TradingClient(key, secret, paper=True)


def get_crypto_positions(client) -> dict:
    """Return open crypto positions keyed by Alpaca symbol."""
    positions = {}
    for p in client.get_all_positions():
        if "/" in p.symbol:   # crypto symbols contain /
            positions[p.symbol] = {
                "symbol":         p.symbol,
                "qty":            float(p.qty),
                "avg_entry":      float(p.avg_entry_price),
                "current_price":  float(p.current_price),
                "market_val":     float(p.market_value),
                "unrealized_pnl": float(p.unrealized_pl),
                "unrealized_pct": float(p.unrealized_plpc) * 100,
            }
    return positions


def get_account(client) -> dict:
    acc = client.get_account()
    return {
        "portfolio_value": float(acc.portfolio_value),
        "cash":            float(acc.cash),
        "buying_power":    float(acc.buying_power),
    }


# ─────────────────────────────────────────────
# ORDER HELPERS
# ─────────────────────────────────────────────

def place_crypto_buy(
    client,
    alpaca_symbol: str,
    notional: float,
    reason: str = "",
) -> dict | None:
    """
    Buy crypto using notional (dollar) amount.
    Crypto doesn't support bracket orders — stop placed separately.
    """
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    try:
        req = MarketOrderRequest(
            symbol        = alpaca_symbol,
            notional      = round(notional, 2),
            side          = OrderSide.BUY,
            type          = "market",
            time_in_force = TimeInForce.GTC,
        )
        order = client.submit_order(req)
        log_trade({
            "date":    datetime.now().isoformat(),
            "action":  "BUY",
            "symbol":  alpaca_symbol,
            "notional": notional,
            "reason":  reason,
            "order_id": str(order.id),
            "status":  str(order.status),
        })
        return {"symbol": alpaca_symbol, "notional": notional, "order_id": str(order.id)}
    except Exception as e:
        print(f"    [!] Crypto buy failed for {alpaca_symbol}: {e}")
        return None


def place_crypto_stop(
    client,
    alpaca_symbol: str,
    qty: float,
    stop_price: float,
) -> None:
    """Place a stop loss order for an existing crypto position."""
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    try:
        # Alpaca crypto stop via stop order
        from alpaca.trading.requests import StopOrderRequest
        req = StopOrderRequest(
            symbol        = alpaca_symbol,
            qty           = round(qty, 8),
            side          = OrderSide.SELL,
            type          = "stop",
            time_in_force = TimeInForce.GTC,
            stop_price    = round(stop_price, 6),
        )
        client.submit_order(req)
    except Exception as e:
        print(f"    [!] Stop order failed for {alpaca_symbol}: {e}")


def close_crypto_position(client, alpaca_symbol: str, reason: str = "") -> bool:
    """Close entire crypto position."""
    try:
        client.close_position(alpaca_symbol)
        log_trade({
            "date":     datetime.now().isoformat(),
            "action":   "SELL",
            "symbol":   alpaca_symbol,
            "notional": "",
            "reason":   reason,
            "order_id": "",
            "status":   "closed",
        })
        return True
    except Exception as e:
        print(f"    [!] Close failed for {alpaca_symbol}: {e}")
        return False


# ─────────────────────────────────────────────
# TRADE LOG
# ─────────────────────────────────────────────

def log_trade(row: dict):
    path   = Path(TRADE_LOG_PATH)
    is_new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if is_new:
            writer.writeheader()
        writer.writerow(row)


# ─────────────────────────────────────────────
# DISPLAY
# ─────────────────────────────────────────────

def print_crypto_portfolio(account: dict, positions: dict):
    print(f"\n{'═'*55}")
    print(f"  CRYPTO PORTFOLIO — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'═'*55}")
    print(f"  Portfolio:    ${account['portfolio_value']:>12,.2f}")
    print(f"  Cash:         ${account['cash']:>12,.2f}")
    if positions:
        print(f"\n  {'SYMBOL':<12} {'QTY':>10} {'ENTRY':>10} {'NOW':>10} {'P&L':>10} {'%':>7}")
        print(f"  {'─'*11} {'─'*9} {'─'*9} {'─'*9} {'─'*9} {'─'*6}")
        for sym, p in positions.items():
            pnl_sign = "+" if p["unrealized_pnl"] >= 0 else ""
            print(f"  {sym:<12} {p['qty']:>10.4f} "
                  f"${p['avg_entry']:>8.4f} "
                  f"${p['current_price']:>8.4f} "
                  f"{pnl_sign}${p['unrealized_pnl']:>7.2f} "
                  f"{pnl_sign}{p['unrealized_pct']:>5.1f}%")
    else:
        print("\n  No open crypto positions.")
    print(f"{'═'*55}")


# ─────────────────────────────────────────────
# MAIN TRADING CYCLE
# ─────────────────────────────────────────────

def run_cycle(
    client,
    watchlist: list[str] = None,
    dry_run:   bool = False,
) -> dict:
    """One full crypto trading cycle."""
    print(f"\n[Crypto] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} — scanning full crypto universe...")

    account   = get_account(client)
    positions = get_crypto_positions(client)
    portfolio = account["portfolio_value"]

    print_crypto_portfolio(account, positions)

    # Scan full crypto universe (not just watchlist)
    full_universe = list(CRYPTO_UNIVERSE.keys())
    results = scan_watchlist(full_universe)
    print(f"  Scanned {len(results)} cryptos — finding best setups...")

    print(f"\n  {'SYMBOL':<10} {'SCORE':>5} {'RSI':>6} {'PRICE':>12}  ACTION")
    print(f"  {'─'*9} {'─'*4} {'─'*5} {'─'*11}  {'─'*20}")

    exits   = []
    entries = []

    for r in results:
        sym    = r["alpaca"]
        score  = r["score"]
        in_pos = sym in positions
        action = ""

        if in_pos:
            if score <= EXIT_SCORE_MAX:
                action = "CLOSE"
                exits.append(r)
            else:
                action = "HOLD"
        else:
            if score >= ENTRY_SCORE_MIN and len(positions) < MAX_OPEN_POSITIONS:
                action = "BUY"
                entries.append(r)
            elif score >= ENTRY_SCORE_MIN - 1:
                action = "WATCH"

        icon = "▲" if action == "BUY" else "▼" if action == "CLOSE" else " "
        print(f"  {r['name']:<10} {score:>5} {r['rsi']:>6} ${r['close']:>11}  {icon} {action}")

    # Execute exits
    for r in exits:
        sym = r["alpaca"]
        print(f"\n  ▼ Closing {sym}", end="  ")
        if dry_run:
            print("[DRY RUN]")
        else:
            ok = close_crypto_position(client, sym, reason="Signal flipped")
            print("✓" if ok else "✗")
            if ok:
                positions.pop(sym, None)

    # Execute entries
    for r in entries:
        sym      = r["alpaca"]
        notional = round(portfolio * MAX_POSITION_PCT, 2)
        print(f"\n  ▲ Buying {sym}  ${notional} notional  "
              f"stop=${r['stop']}  target=${r['target']}", end="  ")
        if dry_run:
            print("[DRY RUN]")
            log_trade({"date": datetime.now().isoformat(), "action": "DRY_RUN_BUY",
                       "symbol": sym, "notional": notional,
                       "reason": "Signal strong", "order_id": "", "status": "dry_run"})
        else:
            result = place_crypto_buy(client, sym, notional, reason="Signal strong")
            print("✓" if result else "✗")

    # ── GitHub logging ──────────────────────────────────────────────
    if _LOGGER_AVAILABLE and not dry_run:
        try:
            # Convert crypto results to signals_data format
            crypto_signals = [{
                "ticker": r["alpaca"], "score": r["score"],
                "action": "BUY" if r["alpaca"] in [e["alpaca"] for e in entries] else
                          "CLOSE" if r["alpaca"] in [e["alpaca"] for e in exits] else
                          "WATCH" if r["score"] >= ENTRY_SCORE_MIN - 1 else "HOLD",
                "risk": {"close": r["close"], "atr_pct": r["atr_pct"],
                         "stop_2x_atr": r["stop"], "target_2r": r["target"]},
            } for r in results]
            log_cycle(
                cycle_type = "crypto",
                signals    = crypto_signals,
                account    = account,
                positions  = positions,
                entries    = len(entries),
                exits      = len(exits),
                watch      = [r["alpaca"] for r in results if r["score"] >= ENTRY_SCORE_MIN - 1],
                dry_run    = dry_run,
            )
        except Exception as _log_err:
            print(f"  [logger] Logging failed: {_log_err}")

    print(f"\n  Cycle complete — {len(exits)} exits, {len(entries)} entries")
    return {"account": account, "positions": positions,
            "results": results, "exits": len(exits), "entries": len(entries)}


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="TKC Crypto Trader")
    parser.add_argument("--dry-run",  action="store_true")
    parser.add_argument("--status",   action="store_true")
    args = parser.parse_args()

    client = get_client()

    if args.status:
        acc = get_account(client)
        pos = get_crypto_positions(client)
        print_crypto_portfolio(acc, pos)
    else:
        run_cycle(client,
               watchlist=load_watchlist_from_config("crypto_watchlist", DEFAULT_CRYPTO_WATCHLIST),
               dry_run=args.dry_run)
