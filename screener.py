"""
Screener — TKC Studio
Scans ~600 S&P 500 + Nasdaq 100 stocks and surfaces today's best setups.

Usage:
    python screener.py              # full scan, saves results
    python screener.py --top 20    # show top N picks only
    python screener.py --quick     # scan a curated 100-stock list (faster)

Called from dashboard.py for the Today's Picks tab.
"""

import sys
import argparse
import warnings
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import ta
import time
from datetime import datetime

# ─────────────────────────────────────────────
# TICKER UNIVERSE
# ─────────────────────────────────────────────

# S&P 500 + Nasdaq 100 combined, deduplicated
# Hardcoded so the screener works offline and instantly
# Update this list periodically as index compositions change

SP500_TICKERS = [
    "MMM","AOS","ABT","ABBV","ACN","ADBE","AMD","AES","AFL","A","APD","ABNB","AKAM",
    "ALB","ARE","ALGN","ALLE","LNT","ALL","GOOGL","GOOG","MO","AMZN","AMCR","AEE",
    "AAL","AEP","AXP","AIG","AMT","AWK","AMP","AME","AMGN","APH","ADI","ANSS","AON",
    "APA","APO","AAPL","AMAT","APTV","ACGL","ANET","AJG","AIZ","T","ATO","ADSK","ADP",
    "AZO","AVB","AVY","AXON","BKR","BALL","BAC","BK","BBWI","BAX","BDX","WRB","BRK-B",
    "BBY","TECH","BIIB","BLK","BX","BA","BMY","AVGO","BR","BRO","BF-B","BLDR",
    "BSX","CHRW","CDNS","CZR","CPT","CPB","COF","CAH","KMX","CCL","CARR","CAT",
    "CBOE","CBRE","CDW","CE","COR","CNC","CNP","CF","CRL","SCHW","CHTR","CVX","CMG",
    "CB","CHD","CI","CINF","CTAS","CSCO","C","CFG","CLX","CME","CMS","KO","CTSH",
    "CL","CMCSA","CAG","COP","ED","STZ","CEG","COO","CPRT","GLW","CPAY","CTVA","CSGP",
    "COST","CTRA","CRWD","CCI","CSX","CMI","CVS","DHR","DRI","DVA","DE","DAL",
    "XRAY","DVN","DXCM","FANG","DLR","DFS","DG","DLTR","D","DPZ","DOV","DOW","DHI",
    "DTE","DUK","DD","EMN","ETN","EBAY","ECL","EIX","EW","EA","ELV","EMR","ENPH",
    "ETR","EOG","EPAM","EQT","EFX","EQIX","EQR","ESS","EL","ETSY","EG","EVRG","ES",
    "EXC","EXPE","EXPD","EXR","XOM","FFIV","FDS","FICO","FAST","FRT","FDX","FIS","FITB",
    "FSLR","FE","FI","FMC","F","FTNT","FTV","FOXA","FOX","BEN","FCX","GRMN","IT","GEN",
    "GNRC","GD","GE","GEHC","GEV","GIS","GM","GPC","GILD","GPN","GL","GDDY","GS","HAL",
    "HIG","HAS","HCA","DOC","HSIC","HSY","HES","HPE","HLT","HOLX","HD","HON","HRL",
    "HST","HWM","HPQ","HUBB","HUM","HBAN","HII","IBM","IEX","IDXX","ITW","INCY","IR",
    "PODD","INTC","ICE","IFF","IP","IPG","INTU","ISRG","IVZ","INVH","IQV","IRM","JBHT",
    "JBL","JKHY","J","JNJ","JCI","JPM","K","KVUE","KDP","KEY","KEYS","KMB",
    "KIM","KMI","KKR","KLAC","KHC","KR","LHX","LH","LRCX","LW","LVS","LDOS","LEN",
    "LLY","LIN","LYV","LKQ","LMT","L","LOW","LULU","LYB","MTB","MRO","MPC","MKTX",
    "MAR","MMC","MLM","MAS","MA","MTCH","MKC","MCD","MCK","MDT","MRK","META","MET",
    "MTD","MGM","MCHP","MU","MSFT","MAA","MRNA","MHK","MOH","TAP","MDLZ","MPWR","MNST",
    "MCO","MS","MOS","MSI","MSCI","NDAQ","NTAP","NFLX","NEM","NWSA","NWS","NEE","NKE",
    "NI","NDSN","NSC","NTRS","NOC","NCLH","NRG","NUE","NVDA","NVR","NXPI","ORLY","OXY",
    "ODFL","OMC","ON","OKE","ORCL","OTIS","PCAR","PKG","PLTR","PH","PAYX","PAYC","PYPL",
    "PNR","PEP","PFE","PCG","PM","PSX","PNW","PNC","POOL","PPG","PPL","PFG","PG","PGR",
    "PRU","PEG","PTC","PSA","PHM","QRVO","PWR","QCOM","DGX","RL","RJF","RTX","O","REG",
    "REGN","RF","RSG","RMD","RVTY","ROK","ROL","ROP","ROST","RCL","SPGI","CRM","SBAC",
    "SLB","STX","SRE","NOW","SHW","SPG","SWKS","SJM","SW","SNA","SOLV","SO","LUV","SWK",
    "SBUX","STT","STLD","STE","SYK","SMCI","SYF","SNPS","SYY","TMUS","TROW","TTWO","TPR",
    "TRGP","TGT","TEL","TDY","TFX","TER","TSLA","TXN","TXT","TMO","TJX","TSCO","TT",
    "TDG","TRV","TRMB","TFC","TYL","TSN","USB","UBER","UDR","ULTA","UNP","UAL","UPS",
    "URI","UNH","UHS","VLO","VTR","VLTO","VRSN","VRSK","VZ","VRTX","VIAV","VST","V",
    "VST","WAB","WMT","DIS","WBD","WM","WAT","WEC","WFC","WELL","WST",
    "WDC","WY","WHR","WMB","WTW","GWW","WYNN","XEL","XYL","YUM","ZBRA","ZBH","ZTS",
]

NASDAQ100_EXTRA = [
    "ADSK","AEP","ALGN","AMAT","AMD","AMGN","AMZN","ANSS","ASML","AVGO","AZN",
    "BIIB","BKNG","CDNS","CEG","CHTR","CMCSA","COST","CPRT","CRWD","CSCO","CSX",
    "CTAS","CTSH","DDOG","DLTR","DXCM","EA","EXC","FANG","FAST","FTNT","GILD",
    "GOOG","GOOGL","HON","IDXX","ILMN","INTC","INTU","ISRG","KDP","KHC","KLAC",
    "LCID","LRCX","LULU","MAR","MCHP","MDLZ","META","MNST","MRNA","MRVL","MSFT",
    "MU","NFLX","NXPI","ODFL","ON","ORLY","PANW","PAYX","PCAR","PDD","PEP","PYPL",
    "QCOM","REGN","ROST","SBUX","SIRI","SNPS","TEAM","TMUS","TSLA","TXN",
    "VRSK","VRSN","VRTX","WBD","WDAY","XEL","ZM","ZS",
]

def get_universe(quick: bool = False) -> list[str]:
    """Return deduplicated list of tickers to scan."""
    if quick:
        # Curated 80-stock list covering all sectors
        return sorted(set([
            "AAPL","MSFT","NVDA","GOOGL","AMZN","META","TSLA","AMD","INTC","QCOM",
            "JPM","BAC","GS","MS","WFC","V","MA","AXP","BLK","C",
            "JNJ","PFE","ABBV","MRK","LLY","UNH","CVS","CI","HUM","AMGN",
            "XOM","CVX","COP","SLB","EOG","MPC","VLO","PSX","OXY","HAL",
            "HD","LOW","TGT","WMT","COST","AMZN","TJX","ROST","DG","DLTR",
            "DIS","NFLX","CMCSA","T","VZ","CHTR","WBD","FOXA","OMC",
            "BA","GE","HON","RTX","LMT","NOC","GD","CAT","DE","MMM",
            "KO","PEP","PG","CL","KMB","GIS","CPB","MCD","SBUX","YUM",
            "SPY","QQQ","IWM","GLD","TLT",
        ]))
    return sorted(set(SP500_TICKERS + NASDAQ100_EXTRA))


# ─────────────────────────────────────────────
# SCORING ENGINE
# ─────────────────────────────────────────────

def score_ticker(ticker: str) -> dict | None:
    """Fetch data and compute signal score for one ticker."""
    try:
        import contextlib, io
        with contextlib.redirect_stderr(io.StringIO()):
            df = yf.download(ticker, period="6mo", interval="1d",
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

        # Composite score (-6 to +6)
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

        # Category tags
        tags = []
        if score >= 4:
            tags.append("Strong Buy Signal")
        if rsi < 40 and bbp < 0.20:
            tags.append("Oversold Bounce")
        if atr_pct < 1.5 and rsi < 60:
            tags.append("Stable / Low Volatility")
        if ema21 > ema50 and macdh > 0 and rsi > 45:
            tags.append("Momentum")
        if not tags and score >= 2:
            tags.append("Watch")

        return {
            "ticker":   ticker,
            "score":    score,
            "close":    round(close, 2),
            "rsi":      round(rsi, 1),
            "bbp":      round(bbp, 3),
            "atr_pct":  round(atr_pct, 2),
            "uptrend":  ema21 > ema50,
            "macdh":    round(macdh, 4),
            "stop":     round(close - atr * 2, 2),
            "target":   round(close + atr * 3, 2),
            "tags":     tags,
        }
    except Exception:
        return None


# ─────────────────────────────────────────────
# SCREENER RUN
# ─────────────────────────────────────────────

def run_screen(
    quick:    bool = False,
    top_n:    int  = 15,
    callback  = None,        # optional progress callback(done, total, ticker)
) -> list[dict]:
    """
    Scan the full universe sequentially.
    Returns list of result dicts sorted by score descending.
    callback(done, total, ticker) is called after each ticker if provided.
    """
    universe = get_universe(quick=quick)
    results  = []
    total    = len(universe)

    for i, ticker in enumerate(universe):
        r = score_ticker(ticker)
        if r:
            results.append(r)
        if callback:
            callback(i + 1, total, ticker)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def top_picks(results: list[dict], n: int = 15) -> dict[str, list[dict]]:
    """
    Bucket results into categories and return top N per category.
    Also returns an overall top list.
    """
    categories = {
        "Top Picks Overall":        [],
        "Strong Buy Signal":        [],
        "Oversold Bounce":          [],
        "Stable / Low Volatility":  [],
        "Momentum":                 [],
    }

    for r in results:
        if len(categories["Top Picks Overall"]) < n and r["score"] >= 1:
            categories["Top Picks Overall"].append(r)
        for tag in r["tags"]:
            if tag in categories and len(categories[tag]) < n:
                categories[tag].append(r)

    # Remove empty categories
    return {k: v for k, v in categories.items() if v}


def export_csv(results: list[dict], path: str = "screener_results.csv"):
    rows = [{k: v for k, v in r.items() if k != "tags"} | {"tags": ", ".join(r["tags"])}
            for r in results]
    pd.DataFrame(rows).to_csv(path, index=False)
    print(f"  [✓] Saved {len(rows)} results to {path}")


def print_picks(picks: dict[str, list[dict]]):
    for category, items in picks.items():
        print(f"\n  ── {category} ──")
        print(f"  {'TICKER':<8} {'SCORE':>5} {'RSI':>6} {'CLOSE':>8} "
              f"{'ATR%':>6} {'STOP':>9} {'TARGET':>9}")
        for r in items:
            trend = "↑" if r["uptrend"] else "↓"
            print(f"  {r['ticker']:<8} {r['score']:>5} {r['rsi']:>6} "
                  f"${r['close']:>7} {r['atr_pct']:>5}% "
                  f"${r['stop']:>8} ${r['target']:>8} {trend}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TKC Studio Screener")
    parser.add_argument("--quick",  action="store_true",
                        help="Scan curated 80-stock list instead of full ~600")
    parser.add_argument("--top",    type=int, default=15,
                        help="Number of top picks to show per category (default 15)")
    args = parser.parse_args()

    n = len(get_universe(quick=args.quick))
    print(f"\n  Scanning {n} tickers — this takes ~{n//10}–{n//7} seconds…")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    t0 = time.time()
    done_count = [0]

    def progress(done, total, ticker):
        done_count[0] = done
        pct = done / total * 100
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        print(f"\r  [{bar}] {pct:4.0f}%  {ticker:<6}  {done}/{total}", end="", flush=True)

    results = run_screen(quick=args.quick, top_n=args.top, callback=progress)
    elapsed = time.time() - t0
    print(f"\n\n  Done — {len(results)} results in {elapsed:.0f}s")

    picks = top_picks(results, n=args.top)
    print_picks(picks)
    export_csv(results)
