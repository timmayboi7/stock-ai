"""
Paper Trader — TKC Studio
Phase 5: Alpaca paper trading wired to pipeline signals

Runs on a schedule. Each cycle it:
  1. Pulls fresh signals from pipeline.py
  2. Checks your current Alpaca paper positions
  3. Enters new trades when signals are strong enough
  4. Exits existing trades when signals flip or stop/target is hit
  5. Logs everything to paper_trades.csv

Setup (one time):
  1. Create a free account at https://alpaca.markets
  2. Go to Paper Trading → API Keys → Generate
  3. Add to your .env file:
       ALPACA_API_KEY=PKXXXXXXXXXXXXXXXX
       ALPACA_SECRET_KEY=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
  4. pip install alpaca-py python-dotenv

Run manually:
    python paper_trader.py               # single cycle
    python paper_trader.py --loop        # runs every market day at open
    python paper_trader.py --status      # show portfolio only, no trades

The Alpaca paper account starts with $100,000 in simulated cash.
No real money is ever used.
"""

import os
import sys
import csv
import time
import argparse
import warnings
warnings.filterwarnings("ignore")

from datetime import datetime, date
from pathlib import Path
from dotenv import load_dotenv

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
    GetOrdersRequest,
    GetPortfolioHistoryRequest,
)
from alpaca.trading.enums import (
    OrderSide, TimeInForce, OrderClass, QueryOrderStatus
)

# Import our pipeline
sys.path.insert(0, os.path.dirname(__file__))
from pipeline import (
    fetch_ticker, add_indicators, score_row,
    compute_composite_score, compute_risk, DEFAULT_WATCHLIST,
)

load_dotenv()

# GitHub logger — optional, only runs if GITHUB_TOKEN is set
try:
    from github_logger import log_cycle, log_error, log_portfolio_snapshot, init_repo
    _LOGGER_AVAILABLE = True
except ImportError:
    _LOGGER_AVAILABLE = False


def save_watch_tickers(tickers: list[str]):
    """Save WATCH-grade tickers to config.json for the dashboard watchlist."""
    from pathlib import Path
    import json
    config_path = Path(os.path.dirname(os.path.abspath(__file__))) / "config.json"
    try:
        existing = {}
        if config_path.exists():
            existing = json.loads(config_path.read_text(encoding="utf-8"))
        existing["watchlist"] = tickers
        existing["watchlist_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        config_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        print(f"  [✓] Watchlist updated — {len(tickers)} tickers saved to config.json")
    except Exception as e:
        print(f"  [!] Could not save watchlist: {e}")


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
# CONFIG — tune these to control risk
# ─────────────────────────────────────────────

# Signal thresholds
ENTRY_SCORE_MIN    = 4      # minimum composite score to open a trade (out of 10)
EXIT_SCORE_MAX     = -2     # close long if score drops below this
STRONG_AVOID_SCORE = -4     # never enter if score is this low

# Position sizing — fraction of portfolio per trade
MAX_POSITION_PCT   = 0.05   # max 5% of portfolio per trade
MAX_OPEN_POSITIONS = 6      # max number of positions at once

# Bracket order multipliers (based on ATR)
STOP_ATR_MULT      = 2.0    # stop = price - (ATR × 2)
TARGET_ATR_MULT    = 3.0    # target = price + (ATR × 3) → 1.5:1 reward/risk

# Minimum conviction required from AI (if available)
# Set to None to ignore AI and trade on technicals only
REQUIRED_SENTIMENT  = None   # None | "BULLISH" | "MIXED"
AVOID_SENTIMENT     = "BEARISH"

# Trade log path
TRADE_LOG_PATH = "paper_trades.csv"


# ─────────────────────────────────────────────
# ALPACA CLIENT
# ─────────────────────────────────────────────

def get_client() -> TradingClient:
    key    = os.environ.get("ALPACA_API_KEY")
    secret = os.environ.get("ALPACA_SECRET_KEY")
    if not key or not secret:
        print("\n  [!] Missing Alpaca credentials.")
        print("  Add to your .env file:")
        print("       ALPACA_API_KEY=PKXXXXXXXXXXXXXXXX")
        print("       ALPACA_SECRET_KEY=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX")
        print("  Get them free at: https://alpaca.markets → Paper Trading → API Keys\n")
        sys.exit(1)
    return TradingClient(key, secret, paper=True)


def get_account_summary(client: TradingClient) -> dict:
    acc = client.get_account()
    return {
        "portfolio_value": float(acc.portfolio_value),
        "cash":            float(acc.cash),
        "buying_power":    float(acc.buying_power),
        "equity":          float(acc.equity),
        "long_value":      float(acc.long_market_value),
        "daytrade_count":  acc.daytrade_count,
    }


def get_open_positions(client: TradingClient) -> dict:
    """Returns dict of {symbol: position_dict}."""
    positions = {}
    for p in client.get_all_positions():
        positions[p.symbol] = {
            "symbol":      p.symbol,
            "qty":         float(p.qty),
            "avg_entry":   float(p.avg_entry_price),
            "market_val":  float(p.market_value),
            "unrealized_pnl": float(p.unrealized_pl),
            "unrealized_pct": float(p.unrealized_plpc) * 100,
            "current_price":  float(p.current_price),
        }
    return positions


def is_market_open(client: TradingClient) -> bool:
    clock = client.get_clock()
    return clock.is_open


# ─────────────────────────────────────────────
# ORDER HELPERS
# ─────────────────────────────────────────────

def calc_position_size(portfolio_value: float, price: float,
                        atr: float) -> int:
    """
    ATR-based sizing: risk MAX_POSITION_PCT of portfolio,
    with stop = STOP_ATR_MULT × ATR below entry.
    Returns whole number of shares.
    """
    max_dollars = portfolio_value * MAX_POSITION_PCT
    stop_dist   = atr * STOP_ATR_MULT
    if stop_dist <= 0:
        return 0
    # How many shares before the stop eats more than max_dollars
    size_by_risk = int(max_dollars / stop_dist)
    # Also cap by raw dollar amount
    size_by_cash = int(max_dollars / price) if price > 0 else 0
    return max(1, min(size_by_risk, size_by_cash))


def place_bracket_order(
    client:    TradingClient,
    symbol:    str,
    qty:       int,
    price:     float,
    atr:       float,
    reason:    str = "",
) -> dict | None:
    """
    Submit a bracket order:
      - Buy at market
      - Automatic stop loss at price - (ATR × STOP_ATR_MULT)
      - Automatic take profit at price + (ATR × TARGET_ATR_MULT)
    """
    stop_price   = round(price - atr * STOP_ATR_MULT,   2)
    target_price = round(price + atr * TARGET_ATR_MULT, 2)

    try:
        req = MarketOrderRequest(
            symbol         = symbol,
            qty            = qty,
            side           = OrderSide.BUY,
            type           = "market",
            time_in_force  = TimeInForce.DAY,
            order_class    = OrderClass.BRACKET,
            stop_loss      = StopLossRequest(stop_price=stop_price),
            take_profit    = TakeProfitRequest(limit_price=target_price),
        )
        order = client.submit_order(req)
        log_trade({
            "date":        datetime.now().isoformat(),
            "action":      "BUY",
            "symbol":      symbol,
            "qty":         qty,
            "price":       price,
            "stop":        stop_price,
            "target":      target_price,
            "reason":      reason,
            "order_id":    str(order.id),
            "status":      str(order.status),
        })
        return {
            "symbol":  symbol,
            "qty":     qty,
            "stop":    stop_price,
            "target":  target_price,
            "order_id": str(order.id),
        }
    except Exception as e:
        print(f"    [!] Order failed for {symbol}: {e}")
        return None


def close_position(
    client: TradingClient,
    symbol: str,
    reason: str = "",
    position: dict = None,
) -> bool:
    """Close entire position for a symbol."""
    try:
        client.close_position(symbol)
        log_trade({
            "date":     datetime.now().isoformat(),
            "action":   "SELL",
            "symbol":   symbol,
            "qty":      position.get("qty", 0) if position else 0,
            "price":    position.get("current_price", 0) if position else 0,
            "stop":     "",
            "target":   "",
            "reason":   reason,
            "order_id": "",
            "status":   "closed",
        })
        return True
    except Exception as e:
        print(f"    [!] Close failed for {symbol}: {e}")
        return False


# ─────────────────────────────────────────────
# TRADE LOG
# ─────────────────────────────────────────────

def log_trade(row: dict):
    """Append a trade to the CSV log."""
    path    = Path(TRADE_LOG_PATH)
    is_new  = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if is_new:
            writer.writeheader()
        writer.writerow(row)


# ─────────────────────────────────────────────
# DISPLAY
# ─────────────────────────────────────────────

def print_portfolio(account: dict, positions: dict):
    print(f"\n{'═'*60}")
    print(f"  PAPER PORTFOLIO  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'═'*60}")
    print(f"  Portfolio value : ${account['portfolio_value']:>12,.2f}")
    print(f"  Cash available  : ${account['cash']:>12,.2f}")
    print(f"  Buying power    : ${account['buying_power']:>12,.2f}")
    print(f"  Long positions  : ${account['long_value']:>12,.2f}")

    if positions:
        print(f"\n  {'SYMBOL':<8} {'QTY':>6} {'ENTRY':>9} {'CURRENT':>9} "
              f"{'P&L $':>9} {'P&L %':>7}")
        print(f"  {'─'*7} {'─'*5} {'─'*8} {'─'*8} {'─'*8} {'─'*6}")
        for sym, p in positions.items():
            pnl_color = "+" if p["unrealized_pnl"] >= 0 else ""
            print(
                f"  {sym:<8} {p['qty']:>6.0f} "
                f"${p['avg_entry']:>8.2f} "
                f"${p['current_price']:>8.2f} "
                f"{pnl_color}${p['unrealized_pnl']:>7.2f} "
                f"{pnl_color}{p['unrealized_pct']:>5.1f}%"
            )
    else:
        print("\n  No open positions.")
    print(f"{'═'*60}")


def print_signal_summary(signals_data: list[dict]):
    print(f"\n{'─'*60}")
    print(f"  SIGNAL SCAN")
    print(f"{'─'*60}")
    print(f"  {'TICKER':<8} {'GRADE':<14} {'SCORE':>6}  ACTION")
    print(f"  {'─'*7} {'─'*13} {'─'*5}  {'─'*18}")
    for d in sorted(signals_data, key=lambda x: x["score"], reverse=True):
        action = d.get("action", "")
        icon   = "▲" if "BUY" in action else "▼" if "CLOSE" in action else " "
        print(f"  {d['ticker']:<8} {d['grade']:<14} {d['score']:>3}/10  "
              f"{icon} {action}")


# ─────────────────────────────────────────────
# MAIN TRADING CYCLE
# ─────────────────────────────────────────────

def run_cycle(
    client:    TradingClient,
    watchlist: list[str] = None,
    dry_run:   bool = False,
) -> dict:
    """
    One full trading cycle:
      - Scan signals
      - Close positions that have flipped negative
      - Open new positions where signals are strong

    dry_run=True prints what it would do without placing orders.
    """
    print(f"\n[ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ] Running cycle...")

    # ── Market check ─────────────────────────
    if not is_market_open(client) and not dry_run:
        print("  Market is closed. Skipping order placement.")
        print("  (Use --dry-run to simulate outside market hours.)")

    account   = get_account_summary(client)
    positions = get_open_positions(client)
    portfolio = account["portfolio_value"]

    print_portfolio(account, positions)

    # ── Full universe scan via screener ──────────────────────────────
    print("  Scanning full stock universe (S&P 500 + Nasdaq 100)...")
    try:
        from screener import run_screen
        all_results = run_screen(quick=False)
        print(f"  Scanned {len(all_results)} stocks — finding best setups...")
    except Exception as e:
        print(f"  [!] Screener failed ({e}) — falling back to watchlist")
        all_results = []
        for ticker in watchlist:
            df = fetch_ticker(ticker)
            if df is None: continue
            df = add_indicators(df)
            if df.empty: continue
            signals = score_row(df.iloc[-1])
            score, max_s, grade = compute_composite_score(signals)
            risk = compute_risk(df)
            all_results.append({
                "ticker": ticker, "score": score,
                "close": risk["close"], "atr_pct": risk["atr_pct"],
                "stop": risk["stop_2x_atr"], "target": risk["target_2r"],
            })

    signals_data = []
    for r in all_results:
        ticker      = r["ticker"]
        score       = r["score"]
        close       = r["close"]
        atr         = round(close * r["atr_pct"] / 100, 2)
        in_position = ticker in positions
        action      = ""

        if in_position:
            if score <= EXIT_SCORE_MAX:
                action = "CLOSE — signal flipped"
            else:
                action = "HOLD"
        else:
            if (score >= ENTRY_SCORE_MIN
                    and len(positions) < MAX_OPEN_POSITIONS
                    and score > STRONG_AVOID_SCORE):
                action = "BUY — signal strong"
            elif score >= ENTRY_SCORE_MIN - 1:
                action = "WATCH — near threshold"

        signals_data.append({
            "ticker": ticker, "grade": "N/A",
            "score": score, "action": action,
            "risk": {
                "close":       close,
                "atr":         atr,
                "atr_pct":     r["atr_pct"],
                "stop_2x_atr": r["stop"],
                "stop_1x_atr": round(close - atr, 2),
                "target_2r":   r["target"],
                "target_3r":   round(close + atr * 3, 2),
            },
        })

    print_signal_summary(signals_data)

    # ── Execute exits first ───────────────────
    exits = [d for d in signals_data if d["action"].startswith("CLOSE")]
    if exits:
        print(f"\n  Exits ({len(exits)}):")
    for d in exits:
        sym = d["ticker"]
        print(f"    ▼ Closing {sym} — {d['action']}", end="  ")
        if dry_run:
            print("[DRY RUN]")
        elif is_market_open(client):
            ok = close_position(client, sym,
                                reason=d["action"],
                                position=positions.get(sym))
            print("✓" if ok else "✗")
            if ok:
                positions.pop(sym, None)
        else:
            print("[market closed]")

    # ── Execute entries ───────────────────────
    entries = [d for d in signals_data if d["action"].startswith("BUY")]
    if entries:
        print(f"\n  Entries ({len(entries)}):")
    for d in entries:
        sym   = d["ticker"]
        risk  = d["risk"]
        price = risk["close"]
        atr   = risk["atr"]
        qty   = calc_position_size(portfolio, price, atr)

        stop   = round(price - atr * STOP_ATR_MULT, 2)
        target = round(price + atr * TARGET_ATR_MULT, 2)

        print(f"    ▲ {sym}  qty={qty}  "
              f"price=${price}  stop=${stop}  target=${target}", end="  ")

        if dry_run:
            print("[DRY RUN]")
            log_trade({
                "date": datetime.now().isoformat(), "action": "DRY_RUN_BUY",
                "symbol": sym, "qty": qty, "price": price,
                "stop": stop, "target": target,
                "reason": d["action"], "order_id": "", "status": "dry_run",
            })
        elif is_market_open(client):
            result = place_bracket_order(
                client, sym, qty, price, atr, reason=d["action"]
            )
            print("✓" if result else "✗")
        else:
            print("[market closed]")

    # ── Save WATCH tickers to watchlist ────────────────────────────
    watch_tickers = [
        d["ticker"] for d in signals_data
        if d["action"].startswith("WATCH")
    ]
    if watch_tickers and not dry_run:
        save_watch_tickers(watch_tickers)
        print(f"  Watchlist updated with {len(watch_tickers)} near-threshold tickers")

    # ── GitHub logging ──────────────────────────────────────────────
    if _LOGGER_AVAILABLE and not dry_run:
        try:
            log_cycle(
                cycle_type = "auto",
                signals    = signals_data,
                account    = account,
                positions  = positions,
                entries    = len(entries),
                exits      = len(exits),
                watch      = watch_tickers,
                dry_run    = dry_run,
            )
        except Exception as _log_err:
            print(f"  [logger] Logging failed: {_log_err}")

    # ── Summary ───────────────────────────────
    print(f"\n  Cycle complete — {len(exits)} exits, {len(entries)} entries, {len(watch_tickers)} on watch")
    if dry_run:
        print("  (DRY RUN — no real orders placed)")

    return {
        "account":   account,
        "positions": positions,
        "signals":   signals_data,
        "exits":     len(exits),
        "entries":   len(entries),
        "watch":     watch_tickers,
    }


# ─────────────────────────────────────────────
# LOOP MODE  (runs daily at market open)
# ─────────────────────────────────────────────

def run_loop(client: TradingClient, watchlist: list[str], dry_run: bool):
    """Run every trading day. Waits for market open, then executes."""
    print("\nLoop mode active. Waiting for market open each day.")
    print("Press Ctrl+C to stop.\n")

    last_run_date = None

    try:
        while True:
            today = date.today()
            clock = client.get_clock()

            if clock.is_open and last_run_date != today:
                print(f"\n  Market is open — running cycle for {today}")
                run_cycle(client, watchlist, dry_run=dry_run)
                last_run_date = today
                # Sleep 6 hours before checking again (avoid duplicate runs)
                time.sleep(60 * 60 * 6)
            else:
                next_open = clock.next_open
                now       = datetime.now(next_open.tzinfo)
                wait_secs = (next_open - now).total_seconds()
                wait_hrs  = wait_secs / 3600
                if wait_hrs > 0:
                    print(f"  Market closed. Next open in {wait_hrs:.1f}h "
                          f"({next_open.strftime('%Y-%m-%d %H:%M %Z')})")
                time.sleep(60 * 15)   # check again in 15 min

    except KeyboardInterrupt:
        print("\n\nLoop stopped.")


# ─────────────────────────────────────────────
# PORTFOLIO HISTORY REPORT
# ─────────────────────────────────────────────

def print_history_report(client: TradingClient):
    """Show portfolio P&L over time and recent closed trades."""
    try:
        hist = client.get_portfolio_history(
            GetPortfolioHistoryRequest(period="1M", timeframe="1D")
        )
        if hist.equity:
            start = hist.equity[0]
            end   = hist.equity[-1]
            ret   = (end - start) / start * 100 if start else 0
            print(f"\n  30-day return: {ret:+.2f}%  "
                  f"(${start:,.2f} → ${end:,.2f})")
    except Exception as e:
        print(f"  (Portfolio history unavailable: {e})")

    # Read local trade log
    log_path = Path(TRADE_LOG_PATH)
    if log_path.exists():
        import csv as _csv
        with open(log_path) as f:
            trades = list(_csv.DictReader(f))
        print(f"\n  Trade log ({len(trades)} entries): {TRADE_LOG_PATH}")
        buys  = [t for t in trades if t["action"] in ("BUY",  "DRY_RUN_BUY")]
        sells = [t for t in trades if t["action"] == "SELL"]
        print(f"  Buys: {len(buys)}  |  Sells: {len(sells)}")
        if trades:
            print(f"\n  Recent trades:")
            for t in trades[-8:]:
                print(f"    {t['date'][:10]}  {t['action']:<8} "
                      f"{t['symbol']:<6}  qty={t['qty']}  "
                      f"${t['price']}  {t['reason'][:40]}")


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TKC Studio Paper Trader")
    parser.add_argument("tickers", nargs="*",
                        help="Ticker symbols (default: pipeline watchlist)")
    parser.add_argument("--loop",    action="store_true",
                        help="Run continuously, once per trading day")
    parser.add_argument("--status",  action="store_true",
                        help="Show portfolio status only, no trades")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simulate trades without placing real orders")
    parser.add_argument("--history", action="store_true",
                        help="Show P&L history and trade log")
    args = parser.parse_args()

    watchlist = ([t.upper() for t in args.tickers]
                 if args.tickers else
                 load_watchlist_from_config("watchlist", DEFAULT_WATCHLIST))

    client = get_client()

    if args.status:
        account   = get_account_summary(client)
        positions = get_open_positions(client)
        print_portfolio(account, positions)
        return

    if args.history:
        print_history_report(client)
        return

    if args.loop:
        run_loop(client, watchlist, dry_run=args.dry_run)
    else:
        run_cycle(client, watchlist, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
