"""
Stock AI Dashboard — TKC Studio
All 5 phases in one app.

Tabs:
  Watchlist   — live signals + AI deep-dive per ticker
  Backtest    — run strategy backtests, view equity curves
  Paper Trade — Alpaca paper portfolio, trigger cycles, trade log
  Learn       — glossary of every term the app uses

Run:
    streamlit run dashboard.py
"""

import os
import json
import sys
import time
import warnings
warnings.filterwarnings("ignore")

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import anthropic
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(encoding="utf-8")

# Ensure all modules in the same folder as dashboard.py are importable
# regardless of what directory Streamlit was launched from
_here = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _here)
os.chdir(_here)
from pipeline import fetch_ticker, add_indicators, score_row, compute_composite_score, compute_risk
from sentiment import get_news, get_fundamentals, build_prompt, call_haiku, get_ai_client, detect_backend

# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="Stock AI — TKC Studio",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  .stApp { background-color: #0f1117; color: #e0e0e0; }
  [data-testid="stSidebar"] { background-color: #1a1d27; }
  .card {
    background: #1e2130; border: 1px solid #2d3148;
    border-radius: 10px; padding: 16px 20px; margin-bottom: 12px;
  }
  .badge {
    display: inline-block; padding: 3px 10px; border-radius: 20px;
    font-size: 12px; font-weight: 600; letter-spacing: 0.5px;
  }
  .badge-strong-buy  { background:#0d3320; color:#22c55e; border:1px solid #16a34a; }
  .badge-buy         { background:#0d2b1a; color:#4ade80; border:1px solid #15803d; }
  .badge-neutral     { background:#1e2130; color:#94a3b8; border:1px solid #334155; }
  .badge-sell        { background:#2d1414; color:#f87171; border:1px solid #b91c1c; }
  .badge-strong-sell { background:#3d0f0f; color:#ef4444; border:1px solid #991b1b; }
  .badge-bullish     { background:#0d3320; color:#22c55e; border:1px solid #16a34a; }
  .badge-bearish     { background:#2d1414; color:#f87171; border:1px solid #b91c1c; }
  .badge-mixed       { background:#2d2010; color:#fbbf24; border:1px solid #d97706; }
  [data-testid="metric-container"] {
    background: #1e2130; border: 1px solid #2d3148;
    border-radius: 10px; padding: 12px 16px;
  }
  .news-item {
    border-left: 3px solid #4f6ef7; padding: 8px 12px;
    margin-bottom: 8px; background: #151825; border-radius: 0 6px 6px 0;
  }
  .news-date    { font-size: 11px; color: #64748b; }
  .news-title   { font-size: 13px; color: #e2e8f0; margin: 2px 0; }
  .news-summary { font-size: 12px; color: #94a3b8; }
  .glossary-term { padding: 12px 16px; border-bottom: 1px solid #1e2130; }
  #MainMenu { visibility: hidden; }
  footer    { visibility: hidden; }
  header    { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# PERSISTENT CONFIG
# ─────────────────────────────────────────────

CONFIG_PATH = _here / "config.json"

def load_config() -> dict:
    """Load saved user preferences from config.json."""
    try:
        if CONFIG_PATH.exists():
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def save_config(data: dict):
    """Save user preferences to config.json."""
    try:
        existing = load_config()
        existing.update(data)
        CONFIG_PATH.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    except Exception:
        pass


def init_state():
    defaults = {
        "watchlist":         load_config().get("watchlist", ["NVDA", "GOOGL", "KO", "AMD", "SPY"]),
        "results":           {},
        "selected":          None,
        "last_run":          None,
        "api_key":           os.environ.get("ANTHROPIC_API_KEY", ""),
        "alpaca_key":        os.environ.get("ALPACA_API_KEY", ""),
        "alpaca_sec":        os.environ.get("ALPACA_SECRET_KEY", ""),
        "run_ai":            True,
        "bt_results":        [],
        "paper_portfolio":   {},
        "paper_positions":   {},
        "paper_last_cycle":  None,
        "crypto_results":    [],
        "crypto_positions":  {},
        "crypto_portfolio":  {},
        "crypto_last_cycle": None,
        "dismissed_tips":    load_config().get("dismissed_tips", []),
        "crypto_watchlist":  load_config().get("crypto_watchlist", ["BTC-USD","ETH-USD","SOL-USD","BNB-USD","XRP-USD","ADA-USD","AVAX-USD","DOGE-USD"]),
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

# Refresh watchlist from config on each load to pick up trader auto-updates
_cfg_wl = load_config().get("watchlist")
if _cfg_wl and _cfg_wl != st.session_state.watchlist:
    st.session_state.watchlist = _cfg_wl



# ─────────────────────────────────────────────
# HELP SYSTEM
# ─────────────────────────────────────────────

def tip(tip_id: str, title: str, body: str):
    """
    Dismissible tip banner. Shows once, user can click to hide forever.
    tip_id must be unique per tip.
    """
    if tip_id in st.session_state.dismissed_tips:
        return
    with st.container():
        col_tip, col_x = st.columns([20, 1])
        with col_tip:
            st.info(f"**{title}** — {body}")
        with col_x:
            if st.button("✕", key=f"dismiss_{tip_id}", help="Dismiss this tip"):
                st.session_state.dismissed_tips.append(tip_id)
                save_config({"dismissed_tips": st.session_state.dismissed_tips})
                st.rerun()

def help_box(label: str, content: str):
    """Collapsible ? expander for contextual help."""
    with st.expander(f"ⓘ  {label}"):
        st.markdown(f'<div style="font-size:13px;color:#94a3b8;line-height:1.7;">{content}</div>',
                    unsafe_allow_html=True)

def metric_with_help(label: str, value: str, help_text: str, delta=None):
    """st.metric with a tooltip."""
    st.metric(label=label, value=value, delta=delta, help=help_text)

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

GRADE_BADGE = {
    "STRONG BUY": "badge-strong-buy", "BUY": "badge-buy",
    "NEUTRAL": "badge-neutral", "SELL": "badge-sell", "STRONG SELL": "badge-strong-sell",
}
SENTIMENT_BADGE = {
    "BULLISH": "badge-bullish", "BEARISH": "badge-bearish",
    "NEUTRAL": "badge-neutral", "MIXED":   "badge-mixed",
}

def badge(text, cls):
    return f'<span class="badge {cls}">{text}</span>'

def run_one_ticker_from_df(ticker, df, api_key, run_ai):
    """Score a single ticker from an already-fetched dataframe."""
    df = add_indicators(df)
    if df.empty:
        return {}
    latest  = df.iloc[-1]
    signals = score_row(latest)
    score, max_s, grade = compute_composite_score(signals)
    risk    = compute_risk(df)
    result  = {
        "grade": grade, "score": score, "max_score": max_s,
        "signals": signals, "risk": risk, "df": df,
        "ai": {}, "news": [], "fundamentals": {},
    }
    if run_ai:
        try:
            news   = get_news(ticker)
            funds  = get_fundamentals(ticker)
            client, backend = get_ai_client(api_key if api_key else None)
            if backend != "none":
                prompt = build_prompt(ticker, signals, risk,
                                      grade, f"{score}/{max_s}", news, funds)
                ai = call_haiku(client, prompt)
                if ai:
                    result.update({"ai": ai, "news": news, "fundamentals": funds})
        except Exception as e:
            st.warning(f"AI failed for {ticker}: {e}")
    return result


def run_full_scan():
    from pipeline import fetch_tickers_batch
    watchlist = st.session_state.watchlist
    results   = {}

    # Phase 1 — batch download all tickers in one call
    prog = st.progress(0, text="Downloading market data…")
    batch = fetch_tickers_batch(watchlist)
    prog.progress(0.3, text=f"Got data for {len(batch)} tickers — computing signals…")

    # Phase 2 — compute indicators + signals
    for i, ticker in enumerate(watchlist):
        pct = 0.3 + 0.4 * (i / len(watchlist))
        prog.progress(pct, text=f"Computing signals: {ticker}…")
        if ticker in batch:
            r = run_one_ticker_from_df(
                ticker, batch[ticker].copy(),
                st.session_state.api_key, False)   # AI runs in phase 3
            if r:
                results[ticker] = r

    # Phase 3 — AI analysis (sequential, API rate limit friendly)
    if st.session_state.run_ai:
        for i, ticker in enumerate(list(results.keys())):
            pct = 0.7 + 0.29 * (i / max(len(results), 1))
            prog.progress(pct, text=f"AI analysis: {ticker}…")
            r = results[ticker]
            try:
                news   = get_news(ticker)
                funds  = get_fundamentals(ticker)
                client, backend = get_ai_client(
                    st.session_state.api_key if st.session_state.api_key else None)
                if backend != "none":
                    prompt = build_prompt(ticker, r["signals"], r["risk"],
                                          r["grade"], f"{r['score']}/{r['max_score']}",
                                          news, funds)
                    ai = call_haiku(client, prompt)
                    if ai:
                        results[ticker].update({"ai": ai, "news": news, "fundamentals": funds})
            except Exception as e:
                st.warning(f"AI failed for {ticker}: {e}")

    prog.progress(1.0, text="Done.")
    time.sleep(0.3)
    prog.empty()
    st.session_state.results  = results
    st.session_state.last_run = datetime.now().strftime("%Y-%m-%d %H:%M")
    if not st.session_state.selected and results:
        st.session_state.selected = list(results.keys())[0]


def build_chart(df, risk):
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.55, 0.23, 0.22], vertical_spacing=0.02,
        subplot_titles=["", "RSI (14)", "MACD (12/26/9)"],
    )
    BG = "#0f1117"; GRID = "#1e2130"
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["open"], high=df["high"],
        low=df["low"], close=df["close"], name="Price",
        increasing_line_color="#22c55e", decreasing_line_color="#ef4444",
        increasing_fillcolor="#22c55e", decreasing_fillcolor="#ef4444",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["BBU_20_2.0_2.0"],
        line=dict(color="rgba(99,102,241,0.5)", width=1), showlegend=False), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["BBL_20_2.0_2.0"],
        line=dict(color="rgba(99,102,241,0.5)", width=1),
        fill="tonexty", fillcolor="rgba(99,102,241,0.07)", showlegend=False), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["EMA_21"], name="EMA 21",
        line=dict(color="#f59e0b", width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["EMA_50"], name="EMA 50",
        line=dict(color="#a78bfa", width=1.5)), row=1, col=1)
    if risk:
        fig.add_hline(y=risk["stop_2x_atr"], line_dash="dash",
            line_color="rgba(239,68,68,0.5)", line_width=1,
            annotation_text=f"Stop ${risk['stop_2x_atr']}",
            annotation_font_color="#ef4444", annotation_font_size=10, row=1, col=1)
        fig.add_hline(y=risk["target_2r"], line_dash="dash",
            line_color="rgba(34,197,94,0.5)", line_width=1,
            annotation_text=f"T1 ${risk['target_2r']}",
            annotation_font_color="#22c55e", annotation_font_size=10, row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["RSI_14"],
        line=dict(color="#38bdf8", width=1.5), showlegend=False), row=2, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="rgba(239,68,68,0.4)", row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="rgba(34,197,94,0.4)", row=2, col=1)
    hist   = df["MACDh_12_26_9"]
    colors = ["#22c55e" if v >= 0 else "#ef4444" for v in hist]
    fig.add_trace(go.Bar(x=df.index, y=hist, marker_color=colors,
        showlegend=False, opacity=0.7), row=3, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MACD_12_26_9"],
        line=dict(color="#f59e0b", width=1.3), showlegend=False), row=3, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MACDs_12_26_9"],
        line=dict(color="#a78bfa", width=1.3), showlegend=False), row=3, col=1)
    fig.update_layout(
        height=600, template="plotly_dark",
        paper_bgcolor=BG, plot_bgcolor=BG,
        font=dict(family="monospace", size=11, color="#94a3b8"),
        legend=dict(orientation="h", yanchor="bottom", y=1.01,
                    xanchor="left", x=0, bgcolor="rgba(0,0,0,0)"),
        xaxis_rangeslider_visible=False,
        margin=dict(l=0, r=60, t=28, b=0), hovermode="x unified",
    )
    for i in range(1, 4):
        ax = f"xaxis{i}" if i > 1 else "xaxis"
        ay = f"yaxis{i}" if i > 1 else "yaxis"
        fig.update_layout(**{ax: dict(gridcolor=GRID, zeroline=False),
                              ay: dict(gridcolor=GRID, zeroline=False)})
    fig.update_yaxes(range=[20, 80], row=2, col=1)
    return fig


# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 📈 Stock AI")
    st.markdown('<div style="color:#64748b;font-size:12px;margin-bottom:16px;">TKC Studio</div>',
                unsafe_allow_html=True)

    st.markdown("#### Anthropic API Key")
    api_input = st.text_input("Anthropic Key", type="password",
        value=st.session_state.api_key, placeholder="sk-ant-api03-…",
        label_visibility="collapsed")
    if api_input != st.session_state.api_key:
        st.session_state.api_key = api_input

    run_ai = st.toggle("AI Analysis", value=st.session_state.run_ai)
    st.session_state.run_ai = run_ai
    if run_ai:
        backend = detect_backend()
        if backend == "ollama":
            st.success("Ollama detected — running free local AI", icon="🟢")
        elif backend == "anthropic":
            st.success("Anthropic API ready", icon="🟢")
        elif not st.session_state.api_key:
            st.warning("No AI backend found. Start Ollama or enter Anthropic key.", icon="⚠️")

    st.markdown("#### Alpaca Paper Keys")
    ak = st.text_input("Alpaca API Key", type="password",
        value=st.session_state.alpaca_key, placeholder="PKXXXXXXXX",
        label_visibility="collapsed")
    asc = st.text_input("Alpaca Secret", type="password",
        value=st.session_state.alpaca_sec, placeholder="secret…",
        label_visibility="collapsed")
    if ak  != st.session_state.alpaca_key: st.session_state.alpaca_key = ak
    if asc != st.session_state.alpaca_sec: st.session_state.alpaca_sec = asc
    if not ak:
        st.caption("Free at alpaca.markets → Paper Trading → API Keys")

    st.markdown("---")
    st.markdown("#### Watchlist")

    # Show last update time if available
    last_wl_update = load_config().get("watchlist_updated")
    if last_wl_update:
        st.caption(f"Auto-updated by trader: {last_wl_update}")
    else:
        st.caption("Auto-populated after each trading cycle with near-threshold tickers")

    ticker_input = st.text_area("Tickers (auto-updated by trader, or add manually)",
        value="\n".join(st.session_state.watchlist),
        height=160, label_visibility="collapsed")
    tickers = [t.strip().upper() for t in ticker_input.split("\n") if t.strip()]
    if tickers != st.session_state.watchlist:
        st.session_state.watchlist = tickers
        save_config({"watchlist": tickers})

    st.markdown("---")
    if st.button("⟳  Run Scan", width="stretch", help="Downloads live data for all watchlist tickers, computes technical signals, and runs AI analysis on each one. Takes 30–120 seconds depending on watchlist size and AI backend."):
        run_full_scan()
        st.rerun()

    if st.session_state.last_run:
        st.caption(f"Last scan: {st.session_state.last_run}")

    if st.session_state.results:
        st.markdown("---")
        rows = []
        for tkr, r in st.session_state.results.items():
            ai = r.get("ai", {})
            rows.append({
                "ticker": tkr, "grade": r.get("grade",""),
                "score": r.get("score",""), "close": r.get("risk",{}).get("close",""),
                "recommendation": ai.get("recommendation",""),
                "sentiment": ai.get("sentiment",""),
                "analyst_take": ai.get("analyst_take",""),
            })
        st.download_button("⬇  Download CSV",
            data=pd.DataFrame(rows).to_csv(index=False),
            file_name=f"signals_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv", width="stretch")


# ─────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────

tab_picks, tab_watch, tab_back, tab_paper, tab_crypto, tab_learn = st.tabs([
    "Today's Picks", "Watchlist", "Backtest", "Paper Trade", "Crypto", "Learn",
])



# ═════════════════════════════════════════════
# TAB 0 — TODAY'S PICKS (SCREENER)
# ═════════════════════════════════════════════

with tab_picks:
    st.markdown("### Today's Picks")
    st.markdown(
        '<div style="color:#64748b;font-size:13px;margin-bottom:12px;">' +
        "Scans S&P 500 + Nasdaq 100 and surfaces today's best setups across all categories." +
        '</div>',
        unsafe_allow_html=True)
    tip("picks_intro",
        "How Today's Picks works",
        "The screener scores ~600 stocks using RSI, Bollinger Bands, EMA trend, and MACD. "
        "The top scorers appear here grouped by category. Click \'+ Add to Watchlist\' on any card "
        "to pull up the full AI deep-dive in the Watchlist tab.")
    help_box("What do the categories mean?",
        "<b>Strong Buy Signal</b> — multiple indicators agree strongly. Highest confidence setups.<br><br>"
        "<b>Oversold Bounce</b> — RSI below 40 and price near the lower Bollinger Band. "
        "Stock has been sold off hard and may bounce back.<br><br>"
        "<b>Stable / Low Volatility</b> — moves less than 1.5% per day on average. "
        "Safer, steadier stocks like KO or JNJ.<br><br>"
        "<b>Momentum</b> — price above both moving averages with MACD turning up. "
        "Stock already in an uptrend and accelerating.<br><br>"
        "<b>Score</b> — ranges from -6 to +6. Above +3 is a strong setup. Below 0 avoid."
    )

    sc1, sc2 = st.columns([2, 1])
    with sc1:
        scan_mode = st.radio("Universe", ["Quick (~80 stocks, ~30s)", "Full (~600 stocks, ~3 min)"],
                             horizontal=True)
    with sc2:
        top_n = st.slider("Picks per category", 3, 15, 6)

    run_screen_btn = st.button("🔍  Scan for Picks", type="primary", key="run_screen")

    if "screener_results" not in st.session_state:
        st.session_state.screener_results = []
        st.session_state.screener_ran_at  = None

    if run_screen_btn:
        try:
            from screener import run_screen, top_picks
            quick = "Quick" in scan_mode
            n_tickers = 84 if quick else 600
            prog  = st.progress(0, text="Starting scan…")
            status_box = st.empty()

            def cb(done, total, ticker):
                pct = done / total
                prog.progress(pct, text=f"Scanning {ticker}… ({done}/{total})")

            with st.spinner(""):
                results = run_screen(quick=quick, top_n=top_n, callback=cb)

            prog.empty()
            status_box.empty()
            st.session_state.screener_results = results
            st.session_state.screener_ran_at  = datetime.now().strftime("%Y-%m-%d %H:%M")
            st.success(f"Done — {len(results)} stocks scanned, top picks below.")
        except ImportError:
            st.error("screener.py not found. Put it in the same folder as dashboard.py.")
        except Exception as e:
            st.error(f"Scan failed: {e}")

    results = st.session_state.screener_results
    ran_at  = st.session_state.screener_ran_at

    if results:
        from screener import top_picks as _top_picks
        picks = _top_picks(results, n=top_n)

        if ran_at:
            st.caption(f"Last scan: {ran_at} — {len(results)} stocks")

        # Category tabs inside the picks tab
        if picks:
            cat_names = list(picks.keys())
            cat_tabs  = st.tabs(cat_names)

            for cat_tab, cat_name in zip(cat_tabs, cat_names):
                with cat_tab:
                    items = picks[cat_name]
                    if not items:
                        st.info("No picks in this category from the last scan.")
                        continue

                    # Render pick cards
                    cols_per_row = 3
                    for row_start in range(0, len(items), cols_per_row):
                        row_items = items[row_start:row_start + cols_per_row]
                        cols = st.columns(cols_per_row)
                        for col, r in zip(cols, row_items):
                            with col:
                                trend_icon  = "↑" if r["uptrend"] else "↓"
                                trend_color = "#22c55e" if r["uptrend"] else "#f87171"
                                score_color = "#22c55e" if r["score"] >= 3 else "#f59e0b" if r["score"] >= 1 else "#f87171"
                                tags_html   = " ".join(
                                    f'<span style="background:#1e3a5f;color:#93c5fd;font-size:10px;' +
                                    f'padding:2px 7px;border-radius:10px;margin-right:3px;">{t}</span>'
                                    for t in r["tags"]
                                )
                                st.markdown(f"""
                                <div class="card" style="padding:14px 16px;">
                                  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;">
                                    <div>
                                      <div style="font-size:18px;font-weight:700;color:#e2e8f0;">{r["ticker"]}</div>
                                      <div style="font-size:22px;font-weight:700;color:#e2e8f0;">${r["close"]}</div>
                                    </div>
                                    <div style="text-align:right;">
                                      <div style="font-size:24px;color:{trend_color};">{trend_icon}</div>
                                      <div style="font-size:12px;font-weight:700;color:{score_color};">Score {r["score"]:+d}</div>
                                    </div>
                                  </div>
                                  <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:10px;">
                                    <div>
                                      <div style="font-size:10px;color:#64748b;">RSI</div>
                                      <div style="font-size:13px;font-weight:600;color:#e2e8f0;">{r["rsi"]}</div>
                                    </div>
                                    <div>
                                      <div style="font-size:10px;color:#64748b;">Volatility/day</div>
                                      <div style="font-size:13px;font-weight:600;color:#e2e8f0;">{r["atr_pct"]}%</div>
                                    </div>
                                    <div>
                                      <div style="font-size:10px;color:#f87171;">Stop loss</div>
                                      <div style="font-size:13px;font-weight:600;color:#f87171;">${r["stop"]}</div>
                                    </div>
                                    <div>
                                      <div style="font-size:10px;color:#22c55e;">Target</div>
                                      <div style="font-size:13px;font-weight:600;color:#22c55e;">${r["target"]}</div>
                                    </div>
                                  </div>
                                  <div style="margin-bottom:10px;">{tags_html}</div>
                                  <div style="font-size:10px;color:#64748b;text-align:right;">
                                    Risk/reward: 1:{round(r["target"]-r["close"],2) / max(round(r["close"]-r["stop"],2),0.01):.1f}
                                  </div>
                                </div>
                                """, unsafe_allow_html=True)

                                # Add to watchlist button
                                if st.button(f"+ Add to Watchlist",
                                             key=f"add_{r['ticker']}_{cat_name}"):
                                    if r["ticker"] not in st.session_state.watchlist:
                                        st.session_state.watchlist.append(r["ticker"])
                                        st.success(f"Added {r['ticker']} to watchlist!")
                                    else:
                                        st.info(f"{r['ticker']} already in watchlist.")

        # Full results table
        with st.expander("View all scanned stocks"):
            table_rows = [{
                "Ticker": r["ticker"], "Score": r["score"],
                "Close": f"${r['close']}",
                "RSI": r["rsi"], "ATR%": f"{r['atr_pct']}%",
                "Stop": f"${r['stop']}","Target": f"${r['target']}",
                "Tags": ", ".join(r["tags"]) or "—",
            } for r in results]
            st.dataframe(pd.DataFrame(table_rows), width="stretch", hide_index=True)

            csv_screen = pd.DataFrame(
                [{k: v for k, v in r.items() if k != "tags"} | {"tags": ", ".join(r["tags"])}
                 for r in results]
            ).to_csv(index=False)
            st.download_button("⬇  Download full screener CSV", data=csv_screen,
                file_name=f"screener_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv")
    else:
        st.markdown("""
        <div style="text-align:center;padding:40px 0;">
          <div style="font-size:40px;margin-bottom:12px;">🔍</div>
          <div style="color:#e2e8f0;font-size:16px;margin-bottom:8px;">Hit Scan for Picks to find today's best setups</div>
          <div style="color:#64748b;font-size:13px;">
            Start with Quick mode (~30 seconds).<br>
            Each pick card shows stop loss, price target, and a one-click Add to Watchlist button<br>
            so you can drill into any pick in the Watchlist tab for the full AI deep-dive.
          </div>
        </div>""", unsafe_allow_html=True)
        st.info("**Quick mode** scans 80 stocks in ~30 seconds. **Full mode** scans ~600 stocks in ~3 minutes.")


# ═════════════════════════════════════════════
# TAB 1 — WATCHLIST
# ═════════════════════════════════════════════

with tab_watch:
    results = st.session_state.results

    if not results:
        last_wl_update = load_config().get("watchlist_updated")
        update_msg = f"Last updated by trader: {last_wl_update}" if last_wl_update else "Watchlist will be auto-populated after the first trading cycle runs."
        st.markdown(f"""
        <div style="text-align:center;padding:60px 0;">
          <div style="font-size:48px;margin-bottom:16px;">📡</div>
          <h2 style="color:#e2e8f0;">Your Watch Radar</h2>
          <p style="color:#94a3b8;font-size:15px;max-width:500px;margin:0 auto 12px;">
            This tab shows tickers that are <strong style="color:#f59e0b;">near the buy threshold</strong>
            — stocks the screener flagged as worth monitoring.
          </p>
          <p style="color:#94a3b8;font-size:15px;max-width:500px;margin:0 auto 12px;">
            It updates automatically after each trading cycle (8:30 AM, 11:00 AM, 2:00 PM CT).
          </p>
          <p style="color:#64748b;font-size:13px;margin-top:16px;">{update_msg}</p>
          <p style="color:#64748b;font-size:13px;margin-top:8px;">
            Hit <strong>Run Scan</strong> to analyze the current watchlist with AI.
          </p>
        </div>""", unsafe_allow_html=True)
    else:
        ranked = sorted(results.items(), key=lambda x: x[1]["score"], reverse=True)

        tip("watchlist_tip",
            "Your Watch Radar",
            "This shows tickers near the buy threshold — automatically updated after each trading cycle. "
            "Click any View button to see the full AI analysis. "
            "If a ticker looks good, go to Paper Trade and hit Run Cycle.")

        # Ticker cards — 8 per row, wraps for any watchlist size
        cards_per_row = 8
        for row_start in range(0, len(ranked), cards_per_row):
            row_items = ranked[row_start:row_start + cards_per_row]
            cols = st.columns(len(row_items))
            for i, (tkr, r) in enumerate(row_items):
                with cols[i]:
                    ai        = r.get("ai", {})
                    grade     = r.get("grade","?")
                    close     = r.get("risk",{}).get("close","")
                    rec       = ai.get("recommendation","") if ai else ""
                    sentiment = ai.get("sentiment","") if ai else ""
                    score     = r.get("score",0); max_s = r.get("max_score",10)
                    pc = "#22c55e" if sentiment=="BULLISH" else "#ef4444" if sentiment=="BEARISH" else "#94a3b8"
                    border = "border:2px solid #4f6ef7;" if st.session_state.selected==tkr else ""
                    rec_label = f"<div style='font-size:11px;font-weight:700;color:{pc};margin-top:2px;'>{rec}</div>" if rec else ""
                    st.markdown(f"""
                    <div class="card" style="{border}padding:12px 14px;">
                      <div style="font-size:13px;font-weight:700;color:#e2e8f0;">{tkr}</div>
                      <div style="font-size:18px;font-weight:700;color:{pc};">${close}</div>
                      {badge(grade, GRADE_BADGE.get(grade,"badge-neutral"))}
                      {rec_label}
                      <div style="font-size:11px;color:#64748b;margin-top:4px;">{score}/{max_s}</div>
                    </div>""", unsafe_allow_html=True)
                    if st.button("View", key=f"sel_{tkr}", width="stretch"):
                        st.session_state.selected = tkr
                        st.rerun()

        st.markdown("---")

        # Detail panel
        selected = st.session_state.selected
        if not selected or selected not in results:
            selected = list(results.keys())[0]
        st.session_state.selected = selected

        r       = results[selected]
        df      = r.get("df")
        risk    = r.get("risk", {})
        signals = r.get("signals", [])
        grade   = r.get("grade","N/A")
        score   = r.get("score", 0)
        max_s   = r.get("max_score", 10)
        ai      = r.get("ai", {})
        news    = r.get("news", [])
        funds   = r.get("fundamentals", {})

        c1,c2,c3,c4,c5 = st.columns(5)
        c1.metric("Ticker", selected)
        c2.metric("Close", f"${risk.get('close','')}",
            help="The most recent closing price of this stock.")
        c3.metric("ATR/day", f"${risk.get('atr','')} ({risk.get('atr_pct','')}%)",
            help="Average True Range — how much this stock typically moves per day. "
                 "Higher % = more volatile. Used to calculate stop loss and position size.")
        c4.metric("Tech Score", f"{score}/{max_s}",
            help="Composite signal score from -10 to +10. "
                 "Above +4 = strong buy signal. Below -2 = avoid. Near 0 = mixed signals.")
        c5.metric("AI Call", ai.get("recommendation","—") if ai else "—",
            help="The AI's recommendation based on signals + news + fundamentals. "
                 "BUY = conditions look favorable. WAIT = not yet. AVOID = signals are bearish.")

        st.markdown("<br>", unsafe_allow_html=True)
        chart_col, analysis_col = st.columns([3, 2], gap="medium")

        with chart_col:
            st.markdown(f"#### {selected} — Chart")
            if df is not None and not df.empty:
                st.plotly_chart(build_chart(df, risk), width="stretch",
                                config={"displayModeBar": False})

            st.markdown("#### Technical Signals")
            help_box("What do these signals mean?",
                "<b>RSI (Relative Strength Index)</b> — momentum gauge 0–100. "
                "Below 30 = oversold/possible bounce. Above 70 = overbought/possible pullback.<br><br>"
                "<b>MACD</b> — compares two price averages. Histogram turning green = buying momentum building.<br><br>"
                "<b>BB (Bollinger Bands)</b> — price near lower band = potentially oversold. Near upper band = overextended.<br><br>"
                "<b>EMA</b> — moving average trend. 21 above 50 = uptrend. 21 below 50 = downtrend.<br><br>"
                "<b>ADX</b> — trend strength. Above 25 = strong trend. Below 20 = choppy/no trend."
            )
            for ind, sig, reason in signals:
                icon  = "▲▲" if sig=="STRONG BUY" else "▲" if sig=="BUY" \
                        else "▼▼" if sig=="STRONG SELL" else "▼" if sig=="SELL" else "─"
                bg    = "#0d3320" if "BUY" in sig else "#2d1414" if "SELL" in sig else "#1e2130"
                color = "#22c55e" if "BUY" in sig else "#f87171" if "SELL" in sig else "#94a3b8"
                st.markdown(f"""
                <div style="display:flex;align-items:center;gap:12px;background:{bg};
                            border-radius:6px;padding:8px 14px;margin-bottom:6px;">
                  <span style="color:{color};font-weight:700;min-width:24px;">{icon}</span>
                  <span style="color:#e2e8f0;font-weight:600;min-width:50px;">{ind}</span>
                  <span style="color:{color};font-size:12px;min-width:110px;">{sig}</span>
                  <span style="color:#94a3b8;font-size:12px;">{reason}</span>
                </div>""", unsafe_allow_html=True)

            r2c1,r2c2,r2c3,r2c4 = st.columns(4)
            r2c1.metric("Stop (2xATR)", f"${risk.get('stop_2x_atr','')}",
                help="Sell and cut losses if price drops here. Set at 2× the daily ATR below entry. "
                     "The paper trader uses this automatically.")
            r2c2.metric("Stop (1xATR)", f"${risk.get('stop_1x_atr','')}",
                help="Tighter stop loss at 1× ATR. More aggressive — less room before exit.")
            r2c3.metric("Target 2R", f"${risk.get('target_2r','')}",
                help="Take profit target at 2:1 reward/risk ratio. "
                     "If your stop risks $5, this target makes $10.")
            r2c4.metric("Target 3R", f"${risk.get('target_3r','')}",
                help="More ambitious target at 3:1 reward/risk. Hold longer for bigger gains.")

        with analysis_col:
            if ai:
                rec       = ai.get("recommendation","WAIT")
                conviction= ai.get("conviction","LOW")
                sentiment = ai.get("sentiment","NEUTRAL")
                ib        = ai.get("if_you_buy", {})
                rec_color = "#22c55e" if rec=="BUY" else "#ef4444" if rec=="AVOID" else "#f59e0b"
                rec_icon  = "▲" if rec=="BUY" else "▼" if rec=="AVOID" else "◉"

                st.markdown(f"""
                <div style="background:{'#0d3320' if rec=='BUY' else '#2d1414' if rec=='AVOID' else '#1e2130'};
                            border:1px solid {rec_color};border-radius:12px;
                            padding:20px 24px;margin-bottom:16px;text-align:center;">
                  <div style="font-size:32px;font-weight:800;color:{rec_color};">
                    {rec_icon} {rec}
                  </div>
                  <div style="font-size:13px;color:#94a3b8;margin-top:4px;">
                    Conviction: {conviction} · {sentiment}
                  </div>
                </div>""", unsafe_allow_html=True)

                for label, key, color in [
                    ("What is this stock?",       "plain_summary",         "#64748b"),
                    ("What the charts are saying","what_signals_mean",     "#64748b"),
                    (f"Why {rec}?",               "recommendation_reason", rec_color),
                ]:
                    st.markdown(f"""
                    <div class="card">
                      <div style="font-size:11px;color:{color};font-weight:600;
                                  text-transform:uppercase;letter-spacing:0.8px;margin-bottom:6px;">{label}</div>
                      <div style="font-size:13px;color:#e2e8f0;line-height:1.7;">{ai.get(key,"")}</div>
                    </div>""", unsafe_allow_html=True)

                if ib:
                    st.markdown(f"""
                    <div class="card" style="border-color:#2563eb;">
                      <div style="font-size:11px;color:#93c5fd;font-weight:600;
                                  text-transform:uppercase;letter-spacing:0.8px;margin-bottom:12px;">
                        If you decide to buy
                      </div>
                      <div style="display:grid;gap:10px;">
                        <div>
                          <div style="font-size:11px;color:#64748b;margin-bottom:2px;">Entry</div>
                          <div style="font-size:13px;color:#e2e8f0;">{ib.get("suggested_entry","")}</div>
                        </div>
                        <div>
                          <div style="font-size:11px;color:#f87171;margin-bottom:2px;">Stop loss</div>
                          <div style="font-size:13px;color:#e2e8f0;">{ib.get("stop_loss","")}</div>
                        </div>
                        <div>
                          <div style="font-size:11px;color:#22c55e;margin-bottom:2px;">Take profit</div>
                          <div style="font-size:13px;color:#e2e8f0;">{ib.get("take_profit","")}</div>
                        </div>
                        <div style="background:#151825;border-radius:6px;padding:10px;">
                          <div style="font-size:11px;color:#f59e0b;margin-bottom:2px;">How much to risk</div>
                          <div style="font-size:13px;color:#e2e8f0;">{ib.get("position_size_advice","")}</div>
                        </div>
                      </div>
                    </div>""", unsafe_allow_html=True)

                risks_html = "".join(
                    f'<div style="font-size:12px;color:#fbbf24;padding:5px 0;'
                    f'border-bottom:1px solid #1e2130;">⚑ {r2}</div>'
                    for r2 in ai.get("key_risks", [])
                )
                st.markdown(f"""
                <div class="card">
                  <div style="font-size:11px;color:#f59e0b;font-weight:600;
                              text-transform:uppercase;letter-spacing:0.8px;margin-bottom:8px;">Risks</div>
                  {risks_html}
                  <div style="margin-top:12px;font-size:12px;color:#cbd5e1;line-height:1.6;">
                    {ai.get("risk_in_plain_english","")}
                  </div>
                </div>""", unsafe_allow_html=True)

                st.markdown(f"""
                <div class="card">
                  <div style="font-size:11px;color:#94a3b8;font-weight:600;
                              text-transform:uppercase;letter-spacing:0.8px;margin-bottom:6px;">Keep an eye on</div>
                  <div style="font-size:13px;color:#e2e8f0;line-height:1.7;margin-bottom:14px;">
                    {ai.get("what_to_watch","")}
                  </div>
                  <div style="font-size:11px;color:#94a3b8;font-weight:600;
                              text-transform:uppercase;letter-spacing:0.8px;margin-bottom:6px;">Upcoming events</div>
                  <div style="font-size:13px;color:#e2e8f0;line-height:1.7;margin-bottom:14px;">
                    {ai.get("upcoming_catalysts","")}
                  </div>
                  <div style="background:#151825;border-radius:8px;padding:12px;border-left:3px solid #a78bfa;">
                    <div style="font-size:11px;color:#a78bfa;font-weight:600;
                                text-transform:uppercase;letter-spacing:0.8px;margin-bottom:4px;">Lesson</div>
                    <div style="font-size:12px;color:#cbd5e1;line-height:1.6;">
                      {ai.get("beginner_lesson","")}
                    </div>
                  </div>
                </div>""", unsafe_allow_html=True)

            else:
                st.markdown(f"""
                <div class="card">
                  <div style="margin-bottom:12px;">{badge(grade, GRADE_BADGE.get(grade,"badge-neutral"))}</div>
                  <div style="color:#64748b;font-size:13px;">
                    Enable AI Analysis in the sidebar and run a scan to get plain-English
                    recommendations, risk levels, and what to actually watch.
                  </div>
                </div>""", unsafe_allow_html=True)

            if funds:
                st.markdown("#### Fundamentals")
                for label, val in funds.items():
                    color = "#22c55e" if "buy" in str(val).lower() \
                            else "#f87171" if "sell" in str(val).lower() else "#e2e8f0"
                    st.markdown(f"""
                    <div style="display:flex;justify-content:space-between;padding:6px 0;
                                border-bottom:1px solid #1e2130;">
                      <span style="font-size:12px;color:#64748b;">{label}</span>
                      <span style="font-size:12px;font-weight:600;color:{color};">{val}</span>
                    </div>""", unsafe_allow_html=True)

            if news:
                st.markdown("#### Recent News")
                for item in news[:6]:
                    summ = (f'<div class="news-summary">{item["summary"][:140]}...</div>'
                            if item.get("summary") else "")
                    st.markdown(f"""
                    <div class="news-item">
                      <div class="news-date">{item["date"]}</div>
                      <div class="news-title">{item["title"]}</div>
                      {summ}
                    </div>""", unsafe_allow_html=True)


with tab_back:
    st.markdown("### Backtest Strategies")
    st.markdown(
        '<div style="color:#64748b;font-size:13px;margin-bottom:20px;">'
        'Test how a strategy would have performed over the last 2 years before '
        'trusting it with paper money.</div>', unsafe_allow_html=True)

    tip("backtest_intro",
        "Run this before paper trading",
        "Backtesting shows how a strategy would have performed historically. "
        "If a strategy loses money in the backtest, skip it. "
        "If it makes money AND beats buy-and-hold, it's worth paper trading for 60-90 days to validate.")
    help_box("How to read the results",
        "<b>Return %</b> — total profit or loss over the 2-year test period.<br><br>"
        "<b>vs Buy&Hold</b> — how much better or worse vs just holding the stock. "
        "Positive = strategy added value. Negative = you'd have done better doing nothing.<br><br>"
        "<b>Win %</b> — percentage of trades that were profitable.<br><br>"
        "<b>Profit Factor</b> — dollars won divided by dollars lost. "
        "Above 1.5 is good. Above 2.0 is excellent. Below 1.0 = losing strategy.<br><br>"
        "<b>Max Drawdown</b> — worst losing streak as a percentage. "
        "A 15% drawdown means the portfolio fell 15% from its peak at some point.<br><br>"
        "<b>Grade A/B</b> — A means the strategy passes most quality checks. F = avoid."
    )

    bc1, bc2 = st.columns([2, 1])
    with bc1:
        bt_input = st.text_input("Tickers (comma separated)",
            value=", ".join(st.session_state.watchlist))
    with bc2:
        bt_strat = st.selectbox("Strategy", [
            "All strategies", "RSI + Bollinger Band",
            "EMA 21/50 Cross", "MACD Signal Flip", "20-Day Breakout",
        ])

    if st.button("▶  Run Backtest", type="primary"):
        try:
            from backtest import run as run_backtest
            bt_tickers = [t.strip().upper() for t in bt_input.split(",") if t.strip()]
            strat_map  = {
                "All strategies":       None,
                "RSI + Bollinger Band": ["rsi_bb"],
                "EMA 21/50 Cross":      ["ema_cross"],
                "MACD Signal Flip":     ["macd_signal"],
                "20-Day Breakout":      ["breakout"],
            }
            with st.spinner("Running backtests… (~30 seconds)"):
                st.session_state.bt_results = run_backtest(
                    bt_tickers, strategies=strat_map[bt_strat])
            st.success(f"Done — {len(st.session_state.bt_results)} results")
        except ImportError as e:
            st.error(f"Import error: {e}")
        except Exception as e:
            st.error(f"Backtest error: {e}")

    bt_results = st.session_state.bt_results
    if not bt_results:
        st.info("Choose a strategy and tickers above, then hit **Run Backtest** to see results.")
    if bt_results:
        st.markdown("#### Results")

        # Sort control
        sort_col = st.selectbox("Sort by", [
            "Profit Factor", "Return %", "vs Buy&Hold",
            "Win %", "Max Drawdown", "Trades", "Grade",
        ], key="bt_sort")

        try:
            from backtest import grade_result
        except ImportError:
            def grade_result(r):
                score = 0
                if r.get("return_pct",0) > 0:        score += 1
                if r.get("alpha",0) > 0:              score += 1
                if r.get("win_rate",0) >= 50:         score += 1
                if r.get("profit_factor",0) >= 1.2:   score += 1
                if r.get("sharpe",0) > 0.5:           score += 1
                if r.get("max_dd",99) < 15:           score += 1
                if score >= 5:   return "A"
                elif score >= 4: return "B"
                elif score >= 3: return "C"
                elif score >= 2: return "D"
                else:            return "F"

        table_rows = []
        for r in bt_results:
            g = grade_result(r)
            table_rows.append({
                "Ticker":        r["ticker"],
                "Strategy":      r["strat_name"],
                "Grade":         g,
                "Return %":      round(r["return_pct"], 2),
                "vs Buy&Hold":   round(r["alpha"], 2),
                "Trades":        r["trades"],
                "Win %":         round(r["win_rate"], 1),
                "Profit Factor": round(r["profit_factor"], 2),
                "Max Drawdown":  round(r["max_dd"], 2),
            })

        df_bt = pd.DataFrame(table_rows)
        sort_map = {
            "Profit Factor": "Profit Factor",
            "Return %":      "Return %",
            "vs Buy&Hold":   "vs Buy&Hold",
            "Win %":         "Win %",
            "Max Drawdown":  "Max Drawdown",
            "Trades":        "Trades",
            "Grade":         "Grade",
        }
        asc = sort_col == "Max Drawdown"   # lower drawdown = better
        df_bt = df_bt.sort_values(sort_map[sort_col], ascending=asc)
        st.dataframe(df_bt, width="stretch", hide_index=True)

        st.markdown("#### Equity Curves")
        all_tickers = sorted(set(r["ticker"] for r in bt_results))
        sel_bt = st.selectbox("Ticker", all_tickers, key="bt_sel")
        ticker_bt = [r for r in bt_results if r["ticker"] == sel_bt]

        if ticker_bt:
            fig_bt = go.Figure()
            colors = {"rsi_bb":"#38bdf8","ema_cross":"#f59e0b",
                      "macd_signal":"#a78bfa","breakout":"#34d399"}
            bh = ticker_bt[0]
            fig_bt.add_trace(go.Scatter(x=bh["price_dates"], y=bh["bh_curve"],
                name="Buy & Hold", line=dict(color="#64748b", width=1.5, dash="dot")))
            for r in ticker_bt:
                fig_bt.add_trace(go.Scatter(
                    x=r["dates"], y=r["equity_curve"], name=r["strat_name"],
                    line=dict(color=colors.get(r["strategy"],"#fff"), width=2),
                    hovertemplate=f"<b>{r['strat_name']}</b><br>$%{{y:,.0f}}<extra></extra>"))
            fig_bt.update_layout(
                height=380, template="plotly_dark",
                paper_bgcolor="#0f1117", plot_bgcolor="#0f1117",
                font=dict(color="#94a3b8"),
                yaxis=dict(tickprefix="$", gridcolor="#1e2130"),
                xaxis=dict(gridcolor="#1e2130"),
                legend=dict(orientation="h", y=1.05),
                margin=dict(l=0,r=0,t=20,b=0), hovermode="x unified")
            st.plotly_chart(fig_bt, width="stretch", config={"displayModeBar": False})

        csv_bt = pd.DataFrame([
            {k: v for k, v in r.items()
             if k not in ("equity_curve","dates","trade_log","bh_curve","price_dates")}
            for r in bt_results
        ]).to_csv(index=False)
        st.download_button("⬇  Download results CSV", data=csv_bt,
            file_name="backtest_results.csv", mime="text/csv")
    else:
        st.info("Run a backtest above to see how strategies performed historically.")


# ═════════════════════════════════════════════
# TAB 3 — PAPER TRADE
# ═════════════════════════════════════════════

with tab_paper:
    st.markdown("### Paper Trading — Alpaca")
    st.markdown(
        '<div style="color:#64748b;font-size:13px;margin-bottom:20px;">'
        'Simulated trades. Fake money. Real market conditions. '
        'Run this for 60–90 days before touching real capital.</div>',
        unsafe_allow_html=True)

    tip("paper_intro",
        "How paper trading works",
        "This uses your Alpaca paper account — $100,000 in fake money. "
        "Run Cycle scans all ~600 stocks, finds the best signals, and places trades automatically. "
        "Run for 90 days before considering real money.")
    help_box("What does Run Cycle actually do?",
        "1. Scans the full S&P 500 + Nasdaq 100 for signals<br>"
        "2. Stocks scoring 4/10+ get a <b>buy order</b> placed automatically<br>"
        "3. Each order has an automatic <b>stop loss</b> and <b>take profit</b><br>"
        "4. Positions scoring -2 or lower get <b>closed automatically</b><br>"
        "5. Near-threshold tickers get saved to your Watchlist<br><br>"
        "<b>Dry Run</b> — shows what it would do without placing any orders."
    )

    has_alpaca = bool(st.session_state.alpaca_key and st.session_state.alpaca_sec)

    if not has_alpaca:
        st.warning("Enter your Alpaca paper API keys in the sidebar to connect.", icon="🔑")
        st.markdown("""
        <div class="card">
          <div style="font-size:13px;color:#e2e8f0;line-height:1.8;">
            <strong style="color:#93c5fd;">How to get free Alpaca paper keys (5 minutes):</strong><br>
            1. Go to <strong>alpaca.markets</strong> and sign up free<br>
            2. Switch to <strong>Paper Trading</strong> in the top-left dropdown<br>
            3. Click <strong>API Keys → Generate New Key</strong><br>
            4. Paste both keys into the sidebar fields above<br><br>
            Your paper account starts with <strong>$100,000 in fake cash</strong>.
            No real money ever moves.
          </div>
        </div>""", unsafe_allow_html=True)
    else:
        def get_alpaca_client():
            from alpaca.trading.client import TradingClient
            return TradingClient(
                st.session_state.alpaca_key,
                st.session_state.alpaca_sec,
                paper=True)

        def load_paper_portfolio():
            try:
                client = get_alpaca_client()
                acc    = client.get_account()
                pos    = {}
                for p in client.get_all_positions():
                    pos[p.symbol] = {
                        "qty":            float(p.qty),
                        "avg_entry":      float(p.avg_entry_price),
                        "current_price":  float(p.current_price),
                        "market_val":     float(p.market_value),
                        "unrealized_pnl": float(p.unrealized_pl),
                        "unrealized_pct": float(p.unrealized_plpc) * 100,
                    }
                st.session_state.paper_portfolio = {
                    "portfolio_value": float(acc.portfolio_value),
                    "cash":            float(acc.cash),
                    "buying_power":    float(acc.buying_power),
                    "long_value":      float(acc.long_market_value),
                }
                st.session_state.paper_positions   = pos
                st.session_state.paper_last_cycle  = datetime.now().strftime("%Y-%m-%d %H:%M")
            except Exception as e:
                st.error(f"Alpaca connection failed: {e}")

        pc1, pc2, pc3 = st.columns(3)
        if pc1.button("⟳  Refresh Portfolio"):
            with st.spinner("Connecting…"):
                load_paper_portfolio()
        if pc2.button("▶  Run Trading Cycle", type="primary"):
            try:
                from paper_trader import run_cycle
                client = get_alpaca_client()
                with st.spinner("Running cycle…"):
                    run_cycle(client, dry_run=False)
                load_paper_portfolio()
                st.success("Cycle complete!")
            except ImportError:
                st.error("paper_trader.py not found in the same folder.")
            except Exception as e:
                st.error(f"Cycle failed: {e}")
        if pc3.button("👁  Dry Run"):
            try:
                from paper_trader import run_cycle
                client = get_alpaca_client()
                with st.spinner("Simulating…"):
                    run_cycle(client, dry_run=True)
                st.info("Dry run complete — no orders placed. Check terminal for output.")
            except ImportError:
                st.error("paper_trader.py not found in the same folder.")
            except Exception as e:
                st.error(f"Dry run failed: {e}")

        if not st.session_state.paper_portfolio:
            with st.spinner("Loading portfolio…"):
                load_paper_portfolio()

        port      = st.session_state.paper_portfolio
        positions = st.session_state.paper_positions

        if port:
            pm1,pm2,pm3,pm4 = st.columns(4)
            pm1.metric("Portfolio Value", f"${port['portfolio_value']:,.2f}",
                help="Total value of your paper account — cash + current value of all open positions.")
            pm2.metric("Cash", f"${port['cash']:,.2f}",
                help="Uninvested cash available. New positions are funded from this.")
            pm3.metric("Buying Power", f"${port['buying_power']:,.2f}",
                help="How much you can spend on new trades right now.")
            pm4.metric("In Positions", f"${port['long_value']:,.2f}",
                help="Total current market value of all open stock positions.")

            st.markdown("#### Open Positions")
            if positions:
                rows_p = [{
                    "Symbol":    sym,
                    "Qty":       int(p["qty"]),
                    "Avg Entry": f"${p['avg_entry']:.2f}",
                    "Current":   f"${p['current_price']:.2f}",
                    "P&L $":     f"{'+'if p['unrealized_pnl']>=0 else ''}{p['unrealized_pnl']:.2f}",
                    "P&L %":     f"{'+'if p['unrealized_pct']>=0 else ''}{p['unrealized_pct']:.1f}%",
                } for sym, p in positions.items()]
                st.dataframe(pd.DataFrame(rows_p), width="stretch", hide_index=True)
            else:
                st.info("No open positions. Run a trading cycle to place trades.")

        log_path = Path("paper_trades.csv")
        if log_path.exists():
            st.markdown("#### Trade Log")
            trades_df = pd.read_csv(log_path)
            st.dataframe(trades_df.tail(20)[::-1], width="stretch", hide_index=True)
            st.download_button("⬇  Download full log", data=trades_df.to_csv(index=False),
                file_name="paper_trades.csv", mime="text/csv")
        else:
            st.caption("Trade log appears here after your first cycle.")

        if st.session_state.paper_last_cycle:
            st.caption(f"Last updated: {st.session_state.paper_last_cycle}")



# ═════════════════════════════════════════════
# TAB — CRYPTO
# ═════════════════════════════════════════════

with tab_crypto:
    st.markdown("### Crypto Trading")
    st.markdown(
        '<div style="color:#64748b;font-size:13px;margin-bottom:20px;">'
        "Trades 24/7. Signals + automated paper trading via Alpaca. "
        "Higher volatility — position sizes are 3% max per trade."
        '</div>',
        unsafe_allow_html=True)

    tip("crypto_intro",
        "Crypto is different from stocks",
        "Crypto trades 24/7 with no market hours. "
        "It's more volatile — prices can move 5-10% in a day. "
        "Position sizes are capped at 3% of portfolio vs 5% for stocks.")
    help_box("Crypto signals explained",
        "Scores work -6 to +6 but entry threshold is 3+ (vs 4+ for stocks) "
        "because crypto oversells harder and bounces more aggressively.<br><br>"
        "<b>ATR %/day</b> — daily move average. BTC ~3-4%/day. Small coins ~8-15%/day.<br><br>"
        "<b>Stop</b> = 2.5x ATR below entry. <b>Target</b> = 4x ATR above entry."
    )

    has_alpaca_crypto = bool(st.session_state.alpaca_key and st.session_state.alpaca_sec)

    st.markdown("#### Crypto Watchlist")
    crypto_input = st.text_area(
        "Cryptos (yfinance format e.g. BTC-USD)",
        value="\n".join(st.session_state.crypto_watchlist),
        height=140, key="crypto_wl_input", label_visibility="collapsed")
    new_crypto_wl = [t.strip().upper() for t in crypto_input.split("\n") if t.strip()]
    if new_crypto_wl != st.session_state.crypto_watchlist:
        st.session_state.crypto_watchlist = new_crypto_wl
        save_config({"crypto_watchlist": new_crypto_wl})

    if st.button("📡  Scan Crypto Signals", key="scan_crypto"):
        try:
            from crypto_trader import scan_watchlist
            with st.spinner("Scanning..."):
                st.session_state.crypto_results = scan_watchlist(st.session_state.crypto_watchlist)
            st.success(f"Scanned {len(st.session_state.crypto_results)} cryptos")
        except ImportError:
            st.error("crypto_trader.py not found in the same folder.")
        except Exception as e:
            st.error(f"Scan failed: {e}")

    results_crypto = st.session_state.crypto_results
    if not results_crypto:
        st.info("Hit **Scan Crypto Signals** above to score all cryptos and find the best setups.")
    if results_crypto:
        st.markdown("#### Signals")
        cols_per_row = 4
        for row_start in range(0, len(results_crypto), cols_per_row):
            row_items = results_crypto[row_start:row_start + cols_per_row]
            ccols = st.columns(cols_per_row)
            for col, r in zip(ccols, row_items):
                with col:
                    sc = "#22c55e" if r["score"] >= 3 else "#f59e0b" if r["score"] >= 1 else "#f87171"
                    ti = "↑" if r["uptrend"] else "↓"
                    tc = "#22c55e" if r["uptrend"] else "#f87171"
                    th = "".join(
                        f'<span style="background:#1e3a5f;color:#93c5fd;font-size:10px;'
                        f'padding:2px 6px;border-radius:8px;margin-right:2px;">{t}</span>'
                        for t in r["tags"]
                    )
                    st.markdown(f"""
                    <div class="card" style="padding:12px 14px;">
                      <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
                        <div style="font-size:15px;font-weight:700;color:#e2e8f0;">{r["name"]}</div>
                        <div style="color:{tc};font-size:16px;">{ti}</div>
                      </div>
                      <div style="font-size:16px;font-weight:700;color:#e2e8f0;margin-bottom:8px;">${r["close"]}</div>
                      <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-bottom:6px;">
                        <div><div style="font-size:10px;color:#64748b;">Score</div>
                             <div style="font-size:13px;font-weight:700;color:{sc};">{r["score"]:+d}/6</div></div>
                        <div><div style="font-size:10px;color:#64748b;">RSI</div>
                             <div style="font-size:13px;color:#e2e8f0;">{r["rsi"]}</div></div>
                        <div><div style="font-size:10px;color:#f87171;">Stop</div>
                             <div style="font-size:11px;color:#f87171;">${r["stop"]}</div></div>
                        <div><div style="font-size:10px;color:#22c55e;">Target</div>
                             <div style="font-size:11px;color:#22c55e;">${r["target"]}</div></div>
                      </div>
                      <div style="font-size:10px;color:#64748b;margin-bottom:4px;">ATR {r["atr_pct"]}%/day</div>
                      <div>{th}</div>
                    </div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("#### Crypto Paper Trading")

    if not has_alpaca_crypto:
        st.warning("Enter Alpaca keys in the sidebar to enable trading.", icon="🔑")
    else:
        def get_alpaca_crypto_client():
            from alpaca.trading.client import TradingClient
            return TradingClient(
                st.session_state.alpaca_key,
                st.session_state.alpaca_sec, paper=True)

        def load_crypto_portfolio():
            try:
                from crypto_trader import get_account, get_crypto_positions
                client = get_alpaca_crypto_client()
                st.session_state.crypto_portfolio = get_account(client)
                st.session_state.crypto_positions = get_crypto_positions(client)
                st.session_state.crypto_last_cycle = datetime.now().strftime("%Y-%m-%d %H:%M")
            except Exception as e:
                st.error(f"Connection failed: {e}")

        cc1, cc2, cc3 = st.columns(3)
        if cc1.button("⟳  Refresh", key="refresh_crypto"):
            with st.spinner("Loading..."): load_crypto_portfolio()
        if cc2.button("▶  Run Cycle", type="primary", key="run_crypto_cycle"):
            try:
                from crypto_trader import run_cycle as crypto_run_cycle
                client = get_alpaca_crypto_client()
                with st.spinner("Running crypto cycle..."):
                    crypto_run_cycle(client, dry_run=False)
                load_crypto_portfolio()
                st.success("Cycle complete!")
            except ImportError:
                st.error("crypto_trader.py not found.")
            except Exception as e:
                st.error(f"Cycle failed: {e}")
        if cc3.button("👁  Dry Run", key="dry_crypto_run"):
            try:
                from crypto_trader import run_cycle as crypto_run_cycle
                client = get_alpaca_crypto_client()
                with st.spinner("Simulating..."):
                    crypto_run_cycle(client, dry_run=True)
                st.info("Dry run done — check terminal for output.")
            except ImportError:
                st.error("crypto_trader.py not found.")
            except Exception as e:
                st.error(f"Dry run failed: {e}")

        if not st.session_state.crypto_portfolio:
            with st.spinner("Loading portfolio..."): load_crypto_portfolio()

        cport = st.session_state.crypto_portfolio
        cpos  = st.session_state.crypto_positions

        if cport:
            pm1, pm2, pm3 = st.columns(3)
            pm1.metric("Portfolio Value", f"${cport['portfolio_value']:,.2f}")
            pm2.metric("Cash",            f"${cport['cash']:,.2f}")
            pm3.metric("Buying Power",    f"${cport['buying_power']:,.2f}")

            st.markdown("#### Open Positions")
            if cpos:
                crows = [{
                    "Symbol":    sym,
                    "Qty":       f"{p['qty']:.6f}",
                    "Avg Entry": f"${p['avg_entry']:.4f}",
                    "Current":   f"${p['current_price']:.4f}",
                    "P&L $":     f"{'+'if p['unrealized_pnl']>=0 else ''}{p['unrealized_pnl']:.2f}",
                    "P&L %":     f"{'+'if p['unrealized_pct']>=0 else ''}{p['unrealized_pct']:.1f}%",
                } for sym, p in cpos.items()]
                st.dataframe(pd.DataFrame(crows), width="stretch", hide_index=True)
            else:
                st.info("No open crypto positions. Run a cycle to place trades.")

        log_path_c = Path("crypto_trades.csv")
        if log_path_c.exists():
            st.markdown("#### Trade Log")
            ctrades = pd.read_csv(log_path_c)
            st.dataframe(ctrades.tail(20)[::-1], width="stretch", hide_index=True)
            st.download_button("⬇  Download log", data=ctrades.to_csv(index=False),
                file_name="crypto_trades.csv", mime="text/csv")
        else:
            st.caption("Trade log appears here after your first cycle.")

        if st.session_state.crypto_last_cycle:
            st.caption(f"Last updated: {st.session_state.crypto_last_cycle}")


# ═════════════════════════════════════════════
# TAB 4 — LEARN
# ═════════════════════════════════════════════

with tab_learn:
    st.markdown("### What does all this mean?")
    st.markdown(
        '<div style="color:#64748b;font-size:13px;margin-bottom:20px;">'
        'Plain English definitions for every term this app uses.</div>',
        unsafe_allow_html=True)

    tip("learn_tip",
        "New to investing?",
        "Start with these 5 terms: RSI, ATR, Stop Loss, Profit Factor, and Paper Trading. "
        "They explain most of what this app does. Use the search box to find any term instantly.")

    terms = [
        ("RSI — Relative Strength Index",
         "A number from 0–100 that shows if a stock has been bought or sold too aggressively. "
         "Below 30 = oversold (potentially a bargain, bounce is likely). Above 70 = overbought "
         "(possibly due for a pullback). Think of it as a temperature gauge for buying and selling pressure."),
        ("MACD — Moving Average Convergence Divergence",
         "Compares two price averages to spot momentum shifts. When the histogram (the bars) flips "
         "from negative to positive, buying momentum is building. When it flips negative, selling is "
         "taking over. The histogram height tells you how strong that shift is."),
        ("Bollinger Bands",
         "Three lines around the price: a middle average and upper/lower boundaries 2 standard deviations away. "
         "Price touching the lower band = potentially oversold and due for a bounce. "
         "Price at the upper band = potentially overextended. The bands squeeze when volatility is low "
         "and expand when volatility is high — a squeeze often precedes a big move."),
        ("EMA — Exponential Moving Average",
         "A smoothed price average that gives more weight to recent prices. "
         "When the 21-day EMA is above the 50-day EMA the stock is in an uptrend (golden cross). "
         "When 21 crosses below 50 (death cross) the trend has turned bearish. "
         "Think of EMAs as the stock's direction of travel on a highway."),
        ("ADX — Average Directional Index",
         "Measures how strong a trend is — not direction, just strength. "
         "Below 20 = weak or choppy, no clear trend. Above 25 = strong trend. "
         "Above 40 = very strong. Only trade in the direction of a strong trend, "
         "never fight a strong trend."),
        ("ATR — Average True Range",
         "The average daily price movement of a stock. ATR of $5 means the stock typically "
         "moves $5 per day. High ATR = volatile stock, trade smaller. "
         "The paper trader uses ATR to size positions and set stop losses automatically."),
        ("Stop Loss",
         "A price where you sell to prevent further loss. You buy at $100, set stop at $90. "
         "If price falls to $90 you sell and lose $10 instead of riding it down to $50. "
         "ALWAYS set a stop before entering a trade. The paper trader does this automatically."),
        ("Take Profit",
         "A price where you sell to lock in a gain. Buy at $100, take profit at $120. "
         "When it hits $120 you sell and pocket $20. Having a target prevents greed "
         "from turning a winner into a loser while you wait for more."),
        ("Position Sizing",
         "How much money to put into one trade. Rule: never risk more than 1–2% of your "
         "total portfolio on a single trade. On $10,000 that means max $100–200 at risk per trade. "
         "The paper trader sizes positions so a stop loss hit costs about 0.3% of portfolio."),
        ("Alpha",
         "The return a strategy earns ABOVE what you'd have made just buying and holding. "
         "Alpha of +5% means the strategy beat doing nothing by 5%. "
         "Negative alpha means the strategy underperformed just holding the stock. "
         "Alpha is the real measure of whether a strategy adds value."),
        ("Profit Factor",
         "Total dollars won divided by total dollars lost across all trades. "
         "Profit factor of 2.0 = for every $1 lost you made $2. Below 1.0 = you lose more "
         "than you win in dollar terms. Look for profit factor above 1.5 before trusting a strategy."),
        ("Bracket Order",
         "A single order that automatically places both a stop loss AND a take profit at the same time. "
         "You enter and Alpaca manages both exits automatically — you don't need to watch the screen. "
         "Every paper trade placed by this app uses bracket orders."),
        ("Paper Trading",
         "Trading with fake money in a real market. Everything looks real but no money moves. "
         "Run this for 60–90 days before risking real capital. If a strategy doesn't work "
         "with fake money it won't work with real money either."),
        ("Conviction",
         "How confident the AI is. HIGH = multiple signals agree strongly, clearer picture. "
         "LOW = mixed or unclear signals. Only act on HIGH conviction calls — "
         "LOW conviction means wait for more clarity before doing anything."),
        ("P/E Ratio — Price to Earnings",
         "How much investors pay for each $1 of company profit. P/E of 20 means you pay "
         "$20 for every $1 the company earns annually. High P/E (50+) = investors expect fast growth. "
         "Low P/E = either a bargain or a struggling company. Neither is automatically good or bad."),
        ("Sentiment",
         "The overall mood toward a stock. Bullish = optimistic, expecting price to rise. "
         "Bearish = pessimistic, expecting a fall. Mixed = signals conflict. "
         "The AI reads news and fundamentals to assess current market mood."),
        ("Buy & Hold",
         "The simplest strategy: buy and hold for years regardless of short-term moves. "
         "The backtest tab compares every strategy against buy-and-hold as a baseline. "
         "If your strategy doesn't beat buy-and-hold, just buy an index fund and do nothing."),
    ]

    search = st.text_input("Search terms", placeholder="e.g. RSI, stop loss, ATR…")
    for term, definition in terms:
        if search and search.lower() not in term.lower() and search.lower() not in definition.lower():
            continue
        st.markdown(f"""
        <div class="glossary-term">
          <div style="font-size:14px;font-weight:600;color:#93c5fd;margin-bottom:4px;">{term}</div>
          <div style="font-size:13px;color:#cbd5e1;line-height:1.7;">{definition}</div>
        </div>""", unsafe_allow_html=True)
