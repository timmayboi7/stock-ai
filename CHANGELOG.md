# TKC Studio Stock AI — What's New

A plain-English summary of updates to the app. Most recent changes are at the top.

---

## Latest Updates

### Trading Protection — Stop Loss & Take Profit Reattachment
**What changed:** The app now checks every open position at the start of each trading cycle. If a stop loss or take profit order is missing (which can happen if a trade was placed outside market hours), the app automatically recalculates the correct levels and reattaches them.

**What this means for you:** Your positions are now always protected. You don't need to manually check Alpaca to see if your stops are in place — the app handles it automatically.

---

### Smarter Order Timing
**What changed:** The app now only places buy orders during market hours (9:30 AM – 4:00 PM Eastern). Previously it could attempt orders outside those hours, which caused the stop loss and take profit to be silently cancelled by Alpaca.

**What this means for you:** No more cancelled stops. Every trade placed will have its full protection attached.

---

### Automatic Watch Radar
**What changed:** After each trading cycle, the Watchlist tab now automatically fills with tickers that are close to the buy threshold — stocks the screener flagged as worth monitoring but not quite ready to trade yet.

**What this means for you:** Open the Watchlist tab to see what the system is keeping an eye on. If something looks interesting, you can run a manual scan and trigger a cycle yourself.

---

### Full Market Scanning
**What changed:** The trading cycles now scan the entire S&P 500 + Nasdaq 100 (around 600 stocks) instead of just the tickers you manually added to the watchlist.

**What this means for you:** The app finds the best opportunities across the whole market on its own. You don't need to add anything to the watchlist for trading to work.

---

### Remote Log Monitoring
**What changed:** After every trading cycle, the app sends a summary to a private log repository. This allows Tim to check in on your trading activity remotely.

**What this means for you:** If something isn't working correctly, Tim can see exactly what happened without needing to be at your computer.

---

### Crypto Trading Added
**What changed:** A new Crypto tab was added to the dashboard. The app now scans 18 cryptocurrencies (Bitcoin, Ethereum, Solana, and more) and paper trades them automatically alongside stocks.

**What this means for you:** Your paper portfolio now includes both stocks and crypto. Crypto trades 24/7 so it runs outside normal market hours too.

---

### AI Analysis Improved
**What changed:** Fixed a bug where the AI was receiving placeholder text instead of actual stock data. Every analysis was running without knowing which stock it was analyzing.

**What this means for you:** The AI recommendations in the Watchlist tab are now based on real data for the specific stock you're looking at. Analysis quality should be noticeably better.

---

### In-App Help System
**What changed:** Added helpful tips and explanations throughout the dashboard. Each tab now has a dismissible tip banner explaining what it does, collapsible help boxes explaining the charts and numbers, and tooltips on metrics when you hover over them.

**What this means for you:** Hover over any number you don't recognize and it will explain what it means. Click the ⓘ boxes to learn more about signals, strategies, and how the app works. Tips disappear after you've read them.

---

### Dashboard Always Loads
**What changed:** Fixed several bugs that caused tabs to appear blank when you first opened the app before running a scan.

**What this means for you:** All tabs now show content when you open the app, including the Learn tab glossary and the Backtest setup screen.

---

### Backtesting Fixed
**What changed:** Fixed an error that prevented the backtest from running when you had many tickers in your watchlist. Also fixed the results table so you can sort by any column — Profit Factor, Return %, Win Rate, and more.

**What this means for you:** You can now test trading strategies against your full watchlist without errors, and sort results to find the best-performing strategies easily.

---

### Watchlist Saved Between Sessions
**What changed:** The tickers in your watchlist are now saved to a local file. When you close and reopen the app, your watchlist is exactly as you left it.

**What this means for you:** You no longer need to re-add your tickers every time you open the dashboard.

---

### Faster Market Scans
**What changed:** Stock data is now downloaded in a single batch request instead of one ticker at a time. The signal calculations then run on the downloaded data.

**What this means for you:** The Run Scan button now shows results much faster — roughly 5–10x faster than before for most watchlist sizes.

---

### Dark Theme on All Machines
**What changed:** Added a configuration file that forces the dark theme regardless of your computer's display settings.

**What this means for you:** The dashboard looks the same on your computer as it does on Tim's — dark background, consistent colors, easy to read.

---

## About the App

TKC Studio Stock AI scans the market, analyzes stocks with AI, and practices trading automatically using fake money through Alpaca's paper trading platform. No real money is ever at risk.

The app runs 3 times per day on its own:
- **8:30 AM** Chicago time — market opens
- **11:00 AM** Chicago time — midday check
- **2:00 PM** Chicago time — end of day

*Built by TKC Studio — Chicago, IL*
