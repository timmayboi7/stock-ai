"""
Sentiment Analyzer — TKC Studio
Phase 2: AI analysis on top of Phase 1 signals

Supports two AI backends — uses whichever is available:
  1. Ollama (FREE, local) — runs llama3.1:8b on your PC, no API key needed
     Install: https://ollama.com  then: ollama pull llama3.1:8b
  2. Anthropic Claude Haiku — cloud API, requires ANTHROPIC_API_KEY in .env

Auto-detects which to use: tries Ollama first, falls back to Anthropic.
You can force one with AI_BACKEND=ollama or AI_BACKEND=anthropic in .env

Usage:
    python sentiment.py                    # runs default watchlist
    python sentiment.py AAPL NVDA TSLA     # custom tickers
"""

import os
import sys
import json
import time
import urllib.request
import warnings
warnings.filterwarnings("ignore")

import yfinance as yf
from datetime import datetime

# Anthropic is optional — only imported if needed
try:
    import anthropic as _anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

# Pull from pipeline if available, else run standalone
try:
    from pipeline import run as run_pipeline, DEFAULT_WATCHLIST
    PIPELINE_AVAILABLE = True
except ImportError:
    DEFAULT_WATCHLIST = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "SPY"]
    PIPELINE_AVAILABLE = False

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

# Anthropic config (used if backend = anthropic)
ANTHROPIC_MODEL  = "claude-haiku-4-5-20251001"

# Ollama config (used if backend = ollama)
OLLAMA_URL       = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL     = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")

MAX_TOKENS    = 1400
MAX_NEWS      = 8
RETRY_DELAY   = 2
MAX_RETRIES   = 2


def detect_backend() -> str:
    """
    Auto-detect which AI backend to use.
    Priority: env var override → Ollama (if running) → Anthropic (if key set)
    """
    forced = os.environ.get("AI_BACKEND", "").lower()
    if forced in ("ollama", "anthropic"):
        return forced

    # Try Ollama first (free, local)
    try:
        urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=2)
        return "ollama"
    except Exception:
        pass

    # Fall back to Anthropic
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"

    return "none"


# ─────────────────────────────────────────────
# DATA ASSEMBLY
# ─────────────────────────────────────────────

def get_news(ticker: str) -> list[dict]:
    """Pull recent news from yfinance. Free, no API key needed."""
    try:
        t = yf.Ticker(ticker)
        raw = t.news or []
        headlines = []
        for item in raw:
            c = item.get("content", {})
            if c.get("contentType") not in ("STORY", "VIDEO"):
                continue
            title   = c.get("title", "").strip()
            summary = c.get("summary", "").strip()
            date    = c.get("pubDate", "")[:10]
            if title:
                headlines.append({
                    "date":    date,
                    "title":   title,
                    "summary": summary,
                })
            if len(headlines) >= MAX_NEWS:
                break
        return headlines
    except Exception as e:
        print(f"    [!] News fetch failed for {ticker}: {e}")
        return []


def get_fundamentals(ticker: str) -> dict:
    """Pull key fundamental metrics from yfinance. Free."""
    try:
        info = yf.Ticker(ticker).info
        keys = [
            ("trailingPE",             "Trailing P/E"),
            ("forwardPE",              "Forward P/E"),
            ("priceToBook",            "Price/Book"),
            ("debtToEquity",           "Debt/Equity"),
            ("returnOnEquity",         "Return on Equity"),
            ("revenueGrowth",          "Revenue Growth (YoY)"),
            ("earningsGrowth",         "Earnings Growth (YoY)"),
            ("recommendationKey",      "Analyst consensus"),
            ("targetMeanPrice",        "Analyst price target (mean)"),
            ("numberOfAnalystOpinions","Analyst opinion count"),
            ("shortRatio",             "Short ratio (days to cover)"),
            ("52WeekChange",           "52-week price change"),
        ]
        result = {}
        for key, label in keys:
            val = info.get(key)
            if val is not None:
                # Format percentages nicely
                if key in ("revenueGrowth", "earningsGrowth", "returnOnEquity", "52WeekChange"):
                    result[label] = f"{val * 100:.1f}%"
                elif isinstance(val, float):
                    result[label] = round(val, 2)
                else:
                    result[label] = val
        return result
    except Exception as e:
        print(f"    [!] Fundamentals fetch failed for {ticker}: {e}")
        return {}


# ─────────────────────────────────────────────
# PROMPT BUILDER
# ─────────────────────────────────────────────

def build_prompt(
    ticker:       str,
    signals:      list[tuple],
    risk:         dict,
    tech_grade:   str,
    tech_score:   str,
    news:         list[dict],
    fundamentals: dict,
) -> str:
    sig_block  = "\n".join(
        f"  - {ind} [{sig}]: {reason}"
        for ind, sig, reason in signals
    )
    news_block = "\n".join(
        f"  [{n['date']}] {n['title']}"
        + (f"\n    Summary: {n['summary']}" if n.get("summary") else "")
        for n in news
    ) if news else "  No recent news available."
    fund_block = "\n".join(
        f"  - {k}: {v}" for k, v in fundamentals.items()
    ) if fundamentals else "  No fundamental data available."

    today = datetime.now().strftime('%Y-%m-%d')
    close    = risk.get('close', 'N/A')
    atr      = risk.get('atr', 'N/A')
    stop_2x  = risk.get('stop_2x_atr', 'N/A')
    stop_1x  = risk.get('stop_1x_atr', 'N/A')
    target_2 = risk.get('target_2r', 'N/A')
    target_3 = risk.get('target_3r', 'N/A')

    return f"""You are a professional stock market analyst. Your reader is a beginner investor
who is new to the stock market and does not understand financial jargon.

Your job:
1. Explain what is happening with this stock in plain English
2. Give a clear, honest, direct recommendation — do not hedge everything into uselessness
3. Explain the risk in concrete terms a beginner can understand and act on
4. Teach them one concept this situation illustrates

Rules:
- Never use jargon without immediately explaining it in plain English
- Be direct — a beginner needs WHAT TO DO, not just WHAT IS HAPPENING
- Be honest about uncertainty — do not oversell confidence you do not have
- Position sizing advice must be conservative and responsible

=== {ticker} — {today} ===

WHAT THE PRICE IS DOING:
  - Current price: ${close}
  - Typical daily price swing: ${atr} (the stock normally moves about this much per day)
  - Technical grade: {tech_grade} (score {tech_score})

WHAT THE CHARTS ARE SAYING:
{sig_block}

SUGGESTED RISK LEVELS:
  - Cut loss if price drops to: ${stop_2x} – ${stop_1x}
  - Take profit target: ${target_2} – ${target_3}

COMPANY FINANCIAL HEALTH:
{fund_block}

RECENT NEWS:
{news_block}

Respond ONLY with valid JSON — no markdown fences, no extra text:
{{
  "plain_summary": "2-3 sentences: what is this company, what is the stock doing right now, why does it matter",
  "what_signals_mean": "2-3 sentences translating the chart signals into plain English — what story do they tell together, no jargon",
  "recommendation": "BUY" | "WAIT" | "AVOID",
  "recommendation_reason": "2-3 direct sentences explaining WHY. If risky say so. If timing is bad say so. Be honest.",
  "what_to_watch": "The single most important thing a beginner should monitor. One concrete sentence.",
  "risk_in_plain_english": "How much could you lose and under what scenario. Be honest and specific with dollar amounts if possible.",
  "if_you_buy": {{
    "suggested_entry": "Specific price or condition — e.g. only buy if price is below $X or wait for it to close above $X first",
    "stop_loss": "The price where you sell to cut losses. Explain in one sentence why this level.",
    "take_profit": "The price target to sell for a gain. Explain what reaching this means.",
    "position_size_advice": "What fraction of investable money to use. Be conservative. E.g. no more than 3-5% of what you can afford to lose entirely."
  }},
  "beginner_lesson": "Teach one investing concept this situation illustrates. 2 sentences, plain English.",
  "key_risks": ["first concrete risk in plain English", "second concrete risk", "third concrete risk"],
  "upcoming_catalysts": "What specific event in the next 2-4 weeks could move this stock — earnings date, Fed meeting, product launch, etc.",
  "sentiment": "BULLISH" | "BEARISH" | "NEUTRAL" | "MIXED",
  "conviction": "HIGH" | "MEDIUM" | "LOW"
}}"""


# ─────────────────────────────────────────────
# HAIKU API CALL
# ─────────────────────────────────────────────

def _parse_json(raw: str) -> dict | None:
    """Strip markdown fences and parse JSON from model output."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    # Find first { to last } in case model adds preamble
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start >= 0 and end > start:
        raw = raw[start:end]
    return json.loads(raw)


def _call_ollama(prompt: str) -> dict | None:
    """Call local Ollama instance."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            payload = json.dumps({
                "model":   OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream":  False,
                "format":  "json",
                "options": {"temperature": 0.1, "num_predict": MAX_TOKENS},
            }).encode()
            req = urllib.request.Request(
                f"{OLLAMA_URL}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
            raw = data["message"]["content"]
            return _parse_json(raw)
        except json.JSONDecodeError as e:
            print(f"    [!] JSON parse failed (attempt {attempt+1}): {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
            return None
        except Exception as e:
            print(f"    [!] Ollama error: {e}")
            return None
    return None


def _call_anthropic(client, prompt: str) -> dict | None:
    """Call Anthropic Claude Haiku."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            msg = client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text
            return _parse_json(raw)
        except json.JSONDecodeError as e:
            print(f"    [!] JSON parse failed (attempt {attempt+1}): {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
            return None
        except Exception as e:
            print(f"    [!] Anthropic error: {e}")
            return None
    return None


def call_haiku(client, prompt: str) -> dict | None:
    """
    Unified AI call — works with both Ollama and Anthropic.
    Pass client=None to use Ollama, or an Anthropic client object for Anthropic.
    """
    if client is None:
        return _call_ollama(prompt)
    return _call_anthropic(client, prompt)


# ─────────────────────────────────────────────
# DISPLAY
# ─────────────────────────────────────────────

SENTIMENT_ICON = {
    "BULLISH":  "📈",
    "BEARISH":  "📉",
    "NEUTRAL":  "⟺ ",
    "MIXED":    "⚡",
}

BIAS_ICON = {
    "LONG":  "▲",
    "SHORT": "▼",
    "WAIT":  "◉",
}

def print_analysis(ticker: str, tech_grade: str, tech_score: str, ai: dict):
    s = ai.get("sentiment", "NEUTRAL")
    c = ai.get("conviction", "LOW")
    b = ai.get("trade_idea", {})

    print(f"\n{'─'*62}")
    print(f"  {ticker:<8}  {SENTIMENT_ICON.get(s,'  ')} {s:<10}  conviction: {c:<8}  [{tech_grade} tech]")
    print()
    print(f"  ▲ BULL: {ai.get('bull_thesis','')}")
    print()
    print(f"  ▼ BEAR: {ai.get('bear_thesis','')}")
    print()

    flags = ai.get("key_risk_flags", [])
    if flags:
        print(f"  ⚑  RISK FLAGS:")
        for f in flags:
            print(f"       • {f}")
        print()

    print(f"  ◎  CATALYST: {ai.get('catalyst_watch','')}")
    print()
    print(f"  ✦  ANALYST: {ai.get('analyst_take','')}")
    print()

    if b:
        bias = b.get("bias", "WAIT")
        icon = BIAS_ICON.get(bias, "◉")
        print(f"  {icon}  TRADE IDEA: {bias}")
        print(f"       Entry: {b.get('entry_note','')}")
        print(f"       Invalidation: {b.get('invalidation','')}")


def print_ai_summary(results: dict):
    """Print compact ranked summary with AI sentiment."""
    print(f"\n{'═'*62}")
    print(f"  AI SENTIMENT SUMMARY  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'═'*62}")
    print(f"  {'TICKER':<8} {'SENTIMENT':<10} {'CONVICTION':<12} {'BIAS':<8} {'TECH GRADE'}")
    print(f"  {'─'*7} {'─'*9} {'─'*11} {'─'*7} {'─'*10}")

    for ticker, r in results.items():
        ai = r.get("ai", {})
        if not ai:
            print(f"  {ticker:<8} {'(no AI data)'}")
            continue
        s = ai.get("sentiment", "N/A")
        c = ai.get("conviction", "N/A")
        bias = ai.get("trade_idea", {}).get("bias", "N/A")
        tech = r.get("grade", "N/A")
        print(f"  {ticker:<8} {SENTIMENT_ICON.get(s,'')} {s:<9} {c:<12} {BIAS_ICON.get(bias,'◉')} {bias:<7} {tech}")

    print(f"{'═'*62}")


def export_full_csv(results: dict, path: str = "signals_with_ai.csv"):
    """Export combined technical + AI results to CSV."""
    import csv
    rows = []
    for ticker, r in results.items():
        ai = r.get("ai", {})
        row = {
            "ticker":       ticker,
            "date":         datetime.now().strftime("%Y-%m-%d"),
            "tech_grade":   r.get("grade", ""),
            "tech_score":   r.get("score", ""),
            "close":        r.get("risk", {}).get("close", ""),
            "atr_pct":      r.get("risk", {}).get("atr_pct", ""),
            "sentiment":    ai.get("sentiment", ""),
            "conviction":   ai.get("conviction", ""),
            "bias":         ai.get("trade_idea", {}).get("bias", ""),
            "bull_thesis":  ai.get("bull_thesis", ""),
            "bear_thesis":  ai.get("bear_thesis", ""),
            "risk_flags":   " | ".join(ai.get("key_risk_flags", [])),
            "catalyst":     ai.get("catalyst_watch", ""),
            "analyst_take": ai.get("analyst_take", ""),
            "entry_note":   ai.get("trade_idea", {}).get("entry_note", ""),
            "invalidation": ai.get("trade_idea", {}).get("invalidation", ""),
        }
        rows.append(row)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n  [✓] Full report exported to {path}")


# ─────────────────────────────────────────────
# MAIN ENTRY
# ─────────────────────────────────────────────

def get_ai_client(api_key: str = None):
    """
    Return (client, backend_name) for the best available AI backend.
    client=None means Ollama (no client object needed).
    """
    backend = detect_backend()

    if backend == "ollama":
        print(f"  AI backend: Ollama ({OLLAMA_MODEL}) — free, running locally")
        return None, "ollama"

    if backend == "anthropic":
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if ANTHROPIC_AVAILABLE and key:
            client = _anthropic.Anthropic(api_key=key)
            print(f"  AI backend: Anthropic ({ANTHROPIC_MODEL})")
            return client, "anthropic"

    print("  [!] No AI backend available.")
    print("      Option 1 (free): install Ollama from ollama.com, then: ollama pull llama3.1:8b")
    print("      Option 2: set ANTHROPIC_API_KEY in your .env file")
    return None, "none"


def analyze_watchlist(pipeline_results: dict, api_key: str = None) -> dict:
    """
    Enrich pipeline results with AI sentiment analysis.
    Auto-detects Ollama or Anthropic — uses whichever is available.
    """
    client, backend = get_ai_client(api_key)

    if backend == "none":
        return pipeline_results

    results = pipeline_results.copy()
    delay   = 0.1 if backend == "ollama" else 0.5

    print(f"\nRunning AI analysis on {len(results)} tickers...")

    for ticker, r in results.items():
        print(f"  → {ticker}", end="  ", flush=True)

        news         = get_news(ticker)
        fundamentals = get_fundamentals(ticker)
        prompt       = build_prompt(
            ticker       = ticker,
            signals      = r.get("signals", []),
            risk         = r.get("risk", {}),
            tech_grade   = r.get("grade", "N/A"),
            tech_score   = f"{r.get('score',0)}/{r.get('max_score',10)}",
            news         = news,
            fundamentals = fundamentals,
        )

        ai = call_haiku(client, prompt)
        if ai:
            results[ticker]["ai"]           = ai
            results[ticker]["news"]         = news
            results[ticker]["fundamentals"] = fundamentals
            sentiment  = ai.get("sentiment", "?")
            conviction = ai.get("conviction", "?")
            rec        = ai.get("recommendation", "?")
            print(f"{SENTIMENT_ICON.get(sentiment,'')} {sentiment} / {conviction} / {rec}")
        else:
            results[ticker]["ai"] = {}
            print("(AI analysis failed)")

        time.sleep(delay)

    return results


def run(watchlist: list[str], api_key: str = None):
    """Full pipeline + sentiment run."""

    # Phase 1: Technical pipeline
    if PIPELINE_AVAILABLE:
        print("\n[ PHASE 1: Technical signals ]")
        pipeline_results = run_pipeline(watchlist, export=False)
    else:
        # Minimal stub if pipeline.py isn't present
        print("[!] pipeline.py not found — AI-only mode (no technical signals)")
        pipeline_results = {t: {"grade":"N/A","score":0,"max_score":0,"signals":[],"risk":{}} for t in watchlist}

    # Phase 2: AI sentiment
    print("\n[ PHASE 2: AI sentiment ]")
    enriched = analyze_watchlist(pipeline_results, api_key=api_key)

    # Display
    ai_results = {k: v for k, v in enriched.items() if v.get("ai")}
    if ai_results:
        print_ai_summary(ai_results)
        for ticker, r in sorted(ai_results.items(), key=lambda x: x[1].get("score", 0), reverse=True):
            if r.get("ai"):
                print_analysis(ticker, r.get("grade","?"), f"{r.get('score',0)}/{r.get('max_score',10)}", r["ai"])
        export_full_csv(enriched)

    return enriched


if __name__ == "__main__":
    watchlist = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_WATCHLIST
    watchlist = [t.upper() for t in watchlist]
    run(watchlist)
