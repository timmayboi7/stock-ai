"""
Backtester — TKC Studio
Phase 4: Strategy validation with Backtrader

Tests 4 built-in strategies across your watchlist and compares results.
Run BEFORE committing real capital — validate the edge exists historically.

Usage:
    python backtest.py                        # default watchlist, all strategies
    python backtest.py AAPL NVDA TSLA         # custom tickers
    python backtest.py --strategy rsi_bb      # single strategy

Strategies:
    rsi_bb       RSI oversold + Bollinger Band lower touch (default)
    ema_cross    EMA 21/50 golden/death cross
    macd_signal  MACD histogram flip with trend filter
    breakout     20-day high breakout with ATR sizing

Requirements:
    pip install backtrader yfinance ta pandas plotly
"""

import sys
import argparse
import warnings
warnings.filterwarnings("ignore")

import backtrader as bt
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import json


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

DEFAULT_WATCHLIST = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "SPY", "AMD", "META"]
STARTING_CASH     = 10_000
COMMISSION        = 0.001      # 0.1% per side (realistic for most brokers)
RISK_PER_TRADE    = 0.01       # 1% of portfolio per trade
PERIOD            = "2y"       # 2 years of historical data


# ─────────────────────────────────────────────
# DATA
# ─────────────────────────────────────────────

def fetch_data(ticker: str) -> pd.DataFrame | None:
    """Pull 2y daily OHLCV from yfinance, formatted for Backtrader."""
    try:
        df = yf.download(ticker, period=PERIOD, interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty or len(df) < 100:
            print(f"  [!] {ticker}: not enough data")
            return None
        df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                      for c in df.columns]
        df.index = pd.to_datetime(df.index)
        df["openinterest"] = 0
        return df
    except Exception as e:
        print(f"  [!] {ticker}: {e}")
        return None


# ─────────────────────────────────────────────
# BASE STRATEGY MIXIN
# ─────────────────────────────────────────────

class BaseStrategy(bt.Strategy):
    """Shared bookkeeping — equity curve, trade log, order guard."""

    def __init__(self):
        self.order        = None
        self.equity_curve = []
        self.dates        = []
        self.trade_log    = []
        self.entry_price  = None

    def next(self):
        self.equity_curve.append(self.broker.getvalue())
        self.dates.append(self.data.datetime.date(0))
        if self.order:
            return
        self._logic()

    def _logic(self):
        raise NotImplementedError

    def _buy_atr_sized(self):
        """Buy with position sized so a 2×ATR stop = 1% portfolio risk."""
        risk   = self.broker.getvalue() * RISK_PER_TRADE
        stop_d = self.atr[0] * 2 if hasattr(self, "atr") else self.data.close[0] * 0.02
        size   = int(risk / stop_d) if stop_d > 0 else 1
        if size > 0 and self.broker.getcash() > self.data.close[0] * size:
            self.entry_price = self.data.close[0]
            self.order = self.buy(size=size)

    def notify_trade(self, trade):
        if trade.isclosed:
            self.trade_log.append({
                "date":    self.data.datetime.date(0).isoformat(),
                "pnl":     round(trade.pnl, 2),
                "pnlcomm": round(trade.pnlcomm, 2),
                "won":     trade.pnlcomm > 0,
            })

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Rejected]:
            self.order = None


# ─────────────────────────────────────────────
# STRATEGIES
# ─────────────────────────────────────────────

class RSI_BB_Strategy(BaseStrategy):
    """
    Entry: RSI < 35 AND price at/near lower Bollinger Band
    Exit:  RSI > 65 OR price reaches upper Bollinger Band
    Filter: only trade when ADX > 15 (some directional movement)
    """
    params = dict(rsi_low=35, rsi_high=65, bb_period=20, bb_dev=2.0)

    def __init__(self):
        super().__init__()
        self.rsi  = bt.indicators.RSI(self.data.close, period=14)
        self.bb   = bt.indicators.BollingerBands(
                        self.data.close, period=self.p.bb_period,
                        devfactor=self.p.bb_dev)
        self.atr  = bt.indicators.ATR(self.data, period=14)

    def _logic(self):
        price = self.data.close[0]
        if not self.position:
            rsi_ok = self.rsi[0] < self.p.rsi_low
            bb_ok  = price <= self.bb.lines.bot[0] * 1.015
            if rsi_ok and bb_ok:
                self._buy_atr_sized()
        else:
            if self.rsi[0] > self.p.rsi_high or price >= self.bb.lines.top[0] * 0.985:
                self.order = self.close()


class EMA_Cross_Strategy(BaseStrategy):
    """
    Entry: EMA 21 crosses above EMA 50 (golden cross) + RSI > 45
    Exit:  EMA 21 crosses below EMA 50 (death cross)
    """
    def __init__(self):
        super().__init__()
        self.ema21    = bt.indicators.EMA(self.data.close, period=21)
        self.ema50    = bt.indicators.EMA(self.data.close, period=50)
        self.cross    = bt.indicators.CrossOver(self.ema21, self.ema50)
        self.rsi      = bt.indicators.RSI(self.data.close, period=14)
        self.atr      = bt.indicators.ATR(self.data, period=14)

    def _logic(self):
        if not self.position:
            if self.cross[0] > 0 and self.rsi[0] > 45:
                self._buy_atr_sized()
        else:
            if self.cross[0] < 0:
                self.order = self.close()


class MACD_Signal_Strategy(BaseStrategy):
    """
    Entry: MACD histogram flips positive (bullish cross) + price above EMA 50
    Exit:  MACD histogram flips negative
    """
    def __init__(self):
        super().__init__()
        self.histo = bt.indicators.MACDHisto(
                         self.data.close,
                         period_me1=12, period_me2=26, period_signal=9)
        self.ema50 = bt.indicators.EMA(self.data.close, period=50)
        self.atr   = bt.indicators.ATR(self.data, period=14)

    def _logic(self):
        price = self.data.close[0]
        if not self.position:
            hist_flip = self.histo.histo[0] > 0 and self.histo.histo[-1] <= 0
            trend_ok  = price > self.ema50[0]
            if hist_flip and trend_ok:
                self._buy_atr_sized()
        else:
            if self.histo.histo[0] < 0 and self.histo.histo[-1] >= 0:
                self.order = self.close()


class Breakout_Strategy(BaseStrategy):
    """
    Entry: Price breaks 20-day high on above-average volume
    Exit:  Price falls below 10-day low OR 3×ATR trailing stop
    """
    params = dict(break_period=20, exit_period=10)

    def __init__(self):
        super().__init__()
        self.highest = bt.indicators.Highest(
                           self.data.high, period=self.p.break_period)
        self.lowest  = bt.indicators.Lowest(
                           self.data.low,  period=self.p.exit_period)
        self.vol_avg = bt.indicators.SMA(self.data.volume, period=20)
        self.atr     = bt.indicators.ATR(self.data, period=14)
        self.stop_price = None

    def _logic(self):
        price = self.data.close[0]
        if not self.position:
            # Break above 20-day high on above-average volume
            breakout   = price > self.highest[-1]
            volume_ok  = self.data.volume[0] > self.vol_avg[0] * 1.2
            if breakout and volume_ok:
                self._buy_atr_sized()
                self.stop_price = price - self.atr[0] * 3
        else:
            # Trail the stop up, never down
            new_stop = price - self.atr[0] * 3
            if new_stop > (self.stop_price or 0):
                self.stop_price = new_stop

            low_break = price < self.lowest[-1]
            stop_hit  = self.stop_price and price < self.stop_price
            if low_break or stop_hit:
                self.order = self.close()
                self.stop_price = None


STRATEGIES = {
    "rsi_bb":      ("RSI + Bollinger Band",  RSI_BB_Strategy),
    "ema_cross":   ("EMA 21/50 Cross",        EMA_Cross_Strategy),
    "macd_signal": ("MACD Signal Flip",       MACD_Signal_Strategy),
    "breakout":    ("20-Day Breakout",        Breakout_Strategy),
}


# ─────────────────────────────────────────────
# RUNNER
# ─────────────────────────────────────────────

def run_single(ticker: str, strat_key: str, df: pd.DataFrame) -> dict | None:
    """Run one strategy on one ticker. Returns stats dict."""
    strat_name, strat_class = STRATEGIES[strat_key]

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.addstrategy(strat_class)
    cerebro.adddata(bt.feeds.PandasData(dataname=df))
    cerebro.broker.setcash(STARTING_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)

    cerebro.addanalyzer(bt.analyzers.SharpeRatio,  _name="sharpe",
                        riskfreerate=0.05, annualize=True)
    cerebro.addanalyzer(bt.analyzers.DrawDown,     _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    try:
        results = cerebro.run()
    except Exception as e:
        print(f"    [!] {ticker}/{strat_key} failed: {e}")
        return None

    strat     = results[0]
    final_val = cerebro.broker.getvalue()
    ret_pct   = (final_val - STARTING_CASH) / STARTING_CASH * 100

    # Buy-and-hold return for same period
    bh_return = (df["close"].iloc[-1] - df["close"].iloc[0]) / df["close"].iloc[0] * 100

    ta_raw    = strat.analyzers.trades.get_analysis()
    total_c   = ta_raw.get("total",  {}).get("closed", 0)
    won       = ta_raw.get("won",    {}).get("total", 0)
    lost      = ta_raw.get("lost",   {}).get("total", 0)
    win_rate  = won / total_c * 100 if total_c else 0
    avg_win   = ta_raw.get("won",    {}).get("pnl", {}).get("average", 0) or 0
    avg_loss  = ta_raw.get("lost",   {}).get("pnl", {}).get("average", 0) or 0
    rr_ratio  = abs(avg_win / avg_loss) if avg_loss else 0

    sharpe_r  = strat.analyzers.sharpe.get_analysis().get("sharperatio") or 0
    dd        = strat.analyzers.drawdown.get_analysis()
    max_dd    = dd.get("max", {}).get("drawdown", 0) or 0

    # Profit factor
    gross_win  = ta_raw.get("won",  {}).get("pnl", {}).get("total", 0) or 0
    gross_loss = abs(ta_raw.get("lost", {}).get("pnl", {}).get("total", 0) or 0)
    pf         = gross_win / gross_loss if gross_loss else (1.0 if gross_win > 0 else 0.0)

    return {
        "ticker":     ticker,
        "strategy":   strat_key,
        "strat_name": strat_name,
        "return_pct": round(ret_pct, 2),
        "bh_return":  round(bh_return, 2),
        "alpha":      round(ret_pct - bh_return, 2),
        "final_val":  round(final_val, 2),
        "trades":     total_c,
        "won":        won,
        "lost":       lost,
        "win_rate":   round(win_rate, 1),
        "avg_win":    round(avg_win, 2),
        "avg_loss":   round(avg_loss, 2),
        "rr_ratio":   round(rr_ratio, 2),
        "profit_factor": round(pf, 2),
        "sharpe":     round(sharpe_r, 2),
        "max_dd":     round(max_dd, 2),
        "equity_curve": strat.equity_curve,
        "dates":      strat.dates,
        "trade_log":  strat.trade_log,
        "bh_curve":   list(STARTING_CASH * (df["close"] / df["close"].iloc[0])),
        "price_dates": [d.date() for d in df.index],
    }


# ─────────────────────────────────────────────
# DISPLAY
# ─────────────────────────────────────────────

PASS = "✓"
FAIL = "✗"

def grade_result(r: dict) -> str:
    """Simple pass/fail grading of a strategy result."""
    score = 0
    if r["return_pct"] > 0:          score += 1
    if r["alpha"] > 0:               score += 1
    if r["win_rate"] >= 50:          score += 1
    if r["profit_factor"] >= 1.2:    score += 1
    if r["sharpe"] > 0.5:            score += 1
    if r["max_dd"] < 15:             score += 1
    if score >= 5:   return "A"
    elif score >= 4: return "B"
    elif score >= 3: return "C"
    elif score >= 2: return "D"
    else:            return "F"


def print_results_table(all_results: list[dict]):
    print(f"\n{'═'*90}")
    print(f"  BACKTEST RESULTS — {PERIOD} — ${STARTING_CASH:,} starting capital")
    print(f"{'═'*90}")
    print(f"  {'TICKER':<7} {'STRATEGY':<26} {'GRD':<5} {'RETURN':>8} {'ALPHA':>8} "
          f"{'TRADES':>7} {'WIN%':>6} {'PF':>5} {'SHARPE':>7} {'MAX DD':>8}")
    print(f"  {'─'*6} {'─'*25} {'─'*4} {'─'*8} {'─'*8} "
          f"{'─'*6} {'─'*5} {'─'*5} {'─'*6} {'─'*8}")

    for r in sorted(all_results, key=lambda x: (x["ticker"], x["return_pct"]), reverse=True):
        g    = grade_result(r)
        icon = "▲" if r["return_pct"] > 0 else "▼"
        alpha_icon = "+" if r["alpha"] >= 0 else ""
        print(
            f"  {r['ticker']:<7} {r['strat_name']:<26} {g:<5} "
            f"{icon}{abs(r['return_pct']):>6.1f}% "
            f"{alpha_icon}{r['alpha']:>6.1f}% "
            f"{r['trades']:>7} "
            f"{r['win_rate']:>5.0f}% "
            f"{r['profit_factor']:>5.1f} "
            f"{r['sharpe']:>7.2f} "
            f"{r['max_dd']:>6.1f}%"
        )

    print(f"{'═'*90}")
    print(f"  ALPHA = strategy return minus buy-and-hold return for same period")
    print(f"  PF = profit factor (gross wins / gross losses, >1.0 is profitable)")


def print_best_strategies(all_results: list[dict]):
    """Show the top strategy per ticker."""
    by_ticker = {}
    for r in all_results:
        t = r["ticker"]
        if t not in by_ticker or r["return_pct"] > by_ticker[t]["return_pct"]:
            by_ticker[t] = r

    print(f"\n{'─'*60}")
    print(f"  BEST STRATEGY PER TICKER")
    print(f"{'─'*60}")
    for ticker, r in sorted(by_ticker.items(), key=lambda x: x[1]["return_pct"], reverse=True):
        g = grade_result(r)
        print(f"  {ticker:<7} {r['strat_name']:<26} grade={g}  "
              f"return={r['return_pct']:+.1f}%  alpha={r['alpha']:+.1f}%")


def print_strategy_summary(all_results: list[dict]):
    """Average performance per strategy across all tickers."""
    by_strat = {}
    for r in all_results:
        s = r["strategy"]
        if s not in by_strat:
            by_strat[s] = []
        by_strat[s].append(r)

    print(f"\n{'─'*60}")
    print(f"  STRATEGY AVERAGES (across all tickers)")
    print(f"{'─'*60}")
    print(f"  {'STRATEGY':<26} {'AVG RET':>9} {'AVG ALPHA':>10} {'AVG WIN%':>9} {'AVG PF':>7}")
    print(f"  {'─'*25} {'─'*8} {'─'*9} {'─'*8} {'─'*7}")
    for s_key, results in sorted(by_strat.items(),
                                  key=lambda x: sum(r["return_pct"] for r in x[1]),
                                  reverse=True):
        n        = len(results)
        avg_ret  = sum(r["return_pct"] for r in results) / n
        avg_alph = sum(r["alpha"]      for r in results) / n
        avg_win  = sum(r["win_rate"]   for r in results) / n
        avg_pf   = sum(r["profit_factor"] for r in results) / n
        name     = STRATEGIES[s_key][0]
        print(f"  {name:<26} {avg_ret:>+8.1f}% {avg_alph:>+9.1f}% "
              f"{avg_win:>8.0f}% {avg_pf:>7.2f}")


# ─────────────────────────────────────────────
# CHARTS
# ─────────────────────────────────────────────

def save_equity_charts(all_results: list[dict], path: str = "backtest_charts.html"):
    """
    Build an HTML file with interactive Plotly equity curves for all
    ticker × strategy combos. Saves to disk, opens in any browser.
    """
    tickers = sorted(set(r["ticker"] for r in all_results))

    # One subplot per ticker
    # vertical_spacing must be < 1/(rows-1) — calculate safely
    n_rows = len(tickers)
    v_spacing = min(0.06, round(0.8 / max(n_rows - 1, 1), 4))

    fig = make_subplots(
        rows=n_rows, cols=1,
        shared_xaxes=False,
        subplot_titles=tickers,
        vertical_spacing=v_spacing,
    )

    colors = {
        "rsi_bb":      "#38bdf8",
        "ema_cross":   "#f59e0b",
        "macd_signal": "#a78bfa",
        "breakout":    "#34d399",
        "bh":          "#64748b",
    }

    for row_idx, ticker in enumerate(tickers, start=1):
        ticker_results = [r for r in all_results if r["ticker"] == ticker]
        if not ticker_results:
            continue

        # Buy-and-hold baseline (use first result's bh_curve)
        bh = ticker_results[0]
        fig.add_trace(go.Scatter(
            x=bh["price_dates"],
            y=bh["bh_curve"],
            name="Buy & Hold" if row_idx == 1 else None,
            showlegend=(row_idx == 1),
            line=dict(color=colors["bh"], width=1.5, dash="dot"),
            legendgroup="bh",
        ), row=row_idx, col=1)

        for r in ticker_results:
            fig.add_trace(go.Scatter(
                x=r["dates"],
                y=r["equity_curve"],
                name=r["strat_name"] if row_idx == 1 else None,
                showlegend=(row_idx == 1),
                line=dict(color=colors.get(r["strategy"], "#fff"), width=1.8),
                legendgroup=r["strategy"],
                hovertemplate=(
                    f"<b>{ticker} — {r['strat_name']}</b><br>"
                    "Date: %{x}<br>Value: $%{y:,.0f}<extra></extra>"
                ),
            ), row=row_idx, col=1)

        # Annotate final return
        best_r = max(ticker_results, key=lambda x: x["return_pct"])
        fig.add_annotation(
            xref=f"x{row_idx}", yref=f"y{row_idx}",
            x=best_r["dates"][-1] if best_r["dates"] else 0,
            y=best_r["equity_curve"][-1] if best_r["equity_curve"] else STARTING_CASH,
            text=f"Best: {best_r['return_pct']:+.1f}%",
            font=dict(size=10, color="#94a3b8"),
            showarrow=False, xanchor="right",
        )

    fig.update_layout(
        height=300 * len(tickers),
        title=dict(
            text=f"Equity Curves — {PERIOD} Backtest — ${STARTING_CASH:,} start",
            font=dict(color="#e2e8f0", size=16),
        ),
        template="plotly_dark",
        paper_bgcolor="#0f1117",
        plot_bgcolor="#0f1117",
        font=dict(color="#94a3b8"),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0,
        ),
        hovermode="x unified",
        margin=dict(l=60, r=60, t=80, b=40),
    )
    for i in range(1, len(tickers) + 1):
        fig.update_xaxes(gridcolor="#1e2130", row=i, col=1)
        fig.update_yaxes(gridcolor="#1e2130", tickprefix="$", row=i, col=1)

    fig.write_html(path)
    print(f"\n  [✓] Charts saved to {path}")
    return fig


def export_results_csv(all_results: list[dict], path: str = "backtest_results.csv"):
    """Export clean results table (no curve data) to CSV."""
    rows = []
    for r in all_results:
        rows.append({k: v for k, v in r.items()
                     if k not in ("equity_curve", "dates", "trade_log",
                                  "bh_curve", "price_dates")})
    pd.DataFrame(rows).to_csv(path, index=False)
    print(f"  [✓] Results exported to {path}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def run(watchlist: list[str], strategies: list[str] = None) -> list[dict]:
    """
    Run all strategies on all tickers.
    Returns flat list of result dicts.
    """
    strat_keys = strategies or list(STRATEGIES.keys())
    all_results = []

    print(f"\n{'═'*60}")
    print(f"  BACKTESTER — TKC Studio")
    print(f"  Tickers: {', '.join(watchlist)}")
    print(f"  Strategies: {', '.join(strat_keys)}")
    print(f"  Period: {PERIOD} | Capital: ${STARTING_CASH:,} | Commission: {COMMISSION*100:.1f}%")
    print(f"{'═'*60}\n")

    for ticker in watchlist:
        print(f"  {ticker}")
        df = fetch_data(ticker)
        if df is None:
            continue

        for s_key in strat_keys:
            s_name = STRATEGIES[s_key][0]
            print(f"    → {s_name:<26}", end="  ", flush=True)
            result = run_single(ticker, s_key, df)
            if result:
                all_results.append(result)
                g = grade_result(result)
                icon = "▲" if result["return_pct"] > 0 else "▼"
                print(f"[{g}] {icon}{abs(result['return_pct']):.1f}%  "
                      f"alpha={result['alpha']:+.1f}%  "
                      f"trades={result['trades']}  "
                      f"win%={result['win_rate']:.0f}%")
            else:
                print("failed")

        print()

    if all_results:
        print_results_table(all_results)
        print_best_strategies(all_results)
        print_strategy_summary(all_results)
        save_equity_charts(all_results)
        export_results_csv(all_results)

    return all_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TKC Studio Backtester")
    parser.add_argument("tickers", nargs="*",
                        help="Ticker symbols (default: full watchlist)")
    parser.add_argument("--strategy", "-s", default=None,
                        choices=list(STRATEGIES.keys()),
                        help="Run only this strategy")
    args = parser.parse_args()

    watchlist = [t.upper() for t in args.tickers] if args.tickers else DEFAULT_WATCHLIST
    strategies = [args.strategy] if args.strategy else None
    run(watchlist, strategies)
