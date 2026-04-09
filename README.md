# TKC Studio Stock AI

Automated stock and crypto trading dashboard powered by local and cloud AI. Built by TKC Studio.

---

## What It Does

- Scans the full **S&P 500 + Nasdaq 100** (~600 stocks) and a **18-crypto universe** using technical signals
- Uses **AI** (local Ollama or cloud Anthropic/OpenAI) to generate plain-English analysis for each ticker
- **Paper trades automatically** 3× per day via Alpaca — no manual intervention needed
- Populates a **Watch Radar** with near-threshold tickers for manual monitoring
- Logs all trade activity to a **private GitHub repo** for remote auditing
- Ships with a **professional installer** that sets up everything from scratch on any Windows machine

---

## Tech Stack

- **Python 3.10+**
- **Streamlit** — dashboard UI
- **yfinance + ta** — market data and technical indicators
- **Backtrader** — strategy backtesting
- **Alpaca** — paper trading execution
- **Ollama** — free local AI (llama3.1:8b or llama3.2:3b)
- **Anthropic / OpenAI** — optional cloud AI backends
- **Plotly** — interactive charts
- **Rich** — installer UI

---

## Project Structure

```
stock-ai/
├── dashboard.py          # Main Streamlit app — all 6 tabs
├── pipeline.py           # Data fetching, indicators, signal scoring
├── screener.py           # Full universe scanner (S&P 500 + Nasdaq 100)
├── sentiment.py          # AI analysis — Ollama / Anthropic / OpenAI
├── backtest.py           # Backtrader strategy backtesting
├── paper_trader.py       # Alpaca paper trading automation
├── crypto_trader.py      # Crypto universe scan + paper trading
├── github_logger.py      # Remote log push to GitHub after each cycle
├── installer.py          # Rich UI installer wizard
├── INSTALL.bat           # Entry point — bootstraps Python then runs installer
├── run_trader.bat        # Runs stock + crypto cycles (called by Task Scheduler)
├── setup_autotrader.ps1  # Creates Windows Task Scheduler tasks
└── .streamlit/
    └── config.toml       # Forces dark theme on all machines
```

---

## Setup

### For End Users (Windows)

1. Download and unzip the project folder
2. Double-click **`INSTALL.bat`**
3. Follow the setup wizard — it handles everything:
   - Python installation (if missing)
   - Ollama AI engine installation
   - AI model download
   - Python package installation
   - Alpaca paper trading account walkthrough
   - Windows Task Scheduler automation (3× daily)
   - Desktop shortcut creation

### For Developers

```bash
# Clone the repo
git clone https://github.com/yourusername/stock-ai.git
cd stock-ai

# Install dependencies
pip install yfinance ta pandas anthropic openai streamlit plotly backtrader alpaca-py python-dotenv requests lxml html5lib rich

# Create .env file
cp .env.example .env
# Fill in your keys

# Run the dashboard
streamlit run dashboard.py
```

---

## Configuration

Create a `.env` file in the project root:

```env
# Alpaca Paper Trading (free at alpaca.markets)
ALPACA_API_KEY=PKxxxxxxxxxxxxxxxx
ALPACA_SECRET_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# AI Backend — pick one
AI_BACKEND=ollama              # free, local
# AI_BACKEND=anthropic
# AI_BACKEND=openai

# Ollama (if using local AI)
OLLAMA_MODEL=llama3.1:8b
OLLAMA_URL=http://localhost:11434

# Cloud AI keys (if using cloud backend)
# ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-...

# Remote logging (optional)
# GITHUB_TOKEN=github_pat_...
# GITHUB_REPO=yourusername/tkc-trader-logs
# MACHINE_ID=primary
```

---

## Dashboard Tabs

| Tab | Description |
|---|---|
| **Today's Picks** | Full screener results grouped by signal category |
| **Watchlist** | Auto-populated Watch Radar — near-threshold tickers with AI deep-dive |
| **Backtest** | 4-strategy backtester with equity curves and sortable results |
| **Paper Trade** | Alpaca portfolio, Run Cycle, positions, trade log |
| **Crypto** | Crypto universe signals and paper trading |
| **Learn** | Plain-English glossary of every term the app uses |

---

## Signal Scoring

Scores range from **-6 to +6** based on four indicators:

| Indicator | Bullish | Bearish |
|---|---|---|
| RSI | < 30 = +2, < 45 = +1 | > 70 = -2, > 55 = -1 |
| Bollinger Band % | < 10% = +2, < 25% = +1 | > 90% = -2, > 75% = -1 |
| EMA 21 vs 50 | Above = +1 | Below = -1 |
| MACD Histogram | Positive = +1 | Negative = -1 |

**Entry threshold: 4+** for stocks, **3+** for crypto.

---

## Automated Trading Schedule

Configured for **Chicago (CT)** time:

| Time | Cycle |
|---|---|
| 8:30 AM | Market open scan |
| 11:00 AM | Midday scan |
| 2:00 PM | End of day scan |

Each cycle scans the full universe, places bracket orders on qualifying signals, closes deteriorating positions, and saves near-threshold tickers to the watchlist.

---

## Remote Logging

When `GITHUB_TOKEN` is set in `.env`, each trading cycle pushes a structured JSON log to the configured GitHub repo:

```
tkc-trader-logs/
├── logs/          # Per-cycle trade activity
├── portfolio/     # Daily portfolio snapshots  
├── errors/        # Caught errors
└── summary/
    ├── latest.json          # Most recent cycle (always overwritten)
    └── YYYY-MM-DD_daily.json
```

---

## Backtesting Strategies

Four built-in strategies:

- **RSI + Bollinger Band** — buy oversold bounces
- **EMA 21/50 Cross** — trend following
- **MACD Signal Flip** — momentum shifts
- **20-Day Breakout** — price breakouts above recent highs

Results are graded A–F based on return, alpha over buy-and-hold, win rate, profit factor, Sharpe ratio, and max drawdown.

---

## License

MIT License — see [LICENSE](LICENSE)

---

## Disclaimer

This software is for **educational and paper trading purposes only**. Nothing in this project constitutes financial advice. Past paper trading performance does not guarantee future real trading results. Always do your own research before risking real capital.

---

*Built by TKC Studio — Chicago, IL*