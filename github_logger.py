"""
TKC Studio Stock AI — GitHub Logger
Pushes structured logs to a private GitHub repo after each trading cycle.

Setup:
    1. Create a private repo called 'tkc-trader-logs' on github.com
    2. Generate a personal access token (repo scope only)
    3. Add to .env:
         GITHUB_TOKEN=ghp_...
         GITHUB_REPO=timmayboi7/tkc-trader-logs

Logs pushed:
    - logs/YYYY-MM-DD_HH-MM_cycle.json   — per-cycle trade activity
    - logs/YYYY-MM-DD_portfolio.json      — daily portfolio snapshot
    - errors/YYYY-MM-DD_HH-MM_error.json  — any errors caught
    - summary/latest.json                 — always the most recent cycle (overwritten)
"""

import os
import json
import base64
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

# Load .env explicitly so token is always available regardless of call order
try:
    from dotenv import load_dotenv as _load_dotenv
    from pathlib import Path as _Path
    _env_path = _Path(os.path.dirname(os.path.abspath(__file__))) / ".env"
    _load_dotenv(dotenv_path=_env_path, encoding="utf-8")
except Exception:
    pass

GITHUB_API    = "https://api.github.com"
GITHUB_TOKEN  = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO   = os.environ.get("GITHUB_REPO", "timmayboi7/tkc-trader-logs")
MACHINE_ID    = os.environ.get("MACHINE_ID", "primary")


# ─────────────────────────────────────────────
# CORE PUSH FUNCTION
# ─────────────────────────────────────────────

def _push_file(path: str, content: dict, message: str) -> bool:
    """
    Push a JSON file to the GitHub repo.
    Creates or updates the file at the given path.
    Returns True on success.
    """
    if not GITHUB_TOKEN:
        print("  [logger] No GITHUB_TOKEN set — skipping log push")
        return False

    try:
        encoded = base64.b64encode(
            json.dumps(content, indent=2, default=str).encode()
        ).decode()

        url = f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{path}"

        # Check if file exists (need its SHA to update)
        sha = None
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"token {GITHUB_TOKEN}",
                    "Accept": "application/vnd.github.v3+json",
                }
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                existing = json.loads(resp.read())
                sha = existing.get("sha")
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise

        # Build payload
        payload = {
            "message": message,
            "content": encoded,
            "branch":  "main",
        }
        if sha:
            payload["sha"] = sha

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept":        "application/vnd.github.v3+json",
                "Content-Type":  "application/json",
            },
            method="PUT",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()

        return True

    except Exception as e:
        print(f"  [logger] Push failed: {e}")
        return False


# ─────────────────────────────────────────────
# LOG BUILDERS
# ─────────────────────────────────────────────

def log_cycle(
    cycle_type: str,           # "open" | "midday" | "close" | "manual"
    signals:    list,          # signals_data from run_cycle
    account:    dict,          # account snapshot
    positions:  dict,          # current positions
    entries:    int,
    exits:      int,
    watch:      list,
    dry_run:    bool = False,
    errors:     list = None,
) -> bool:
    """Log a full trading cycle to GitHub."""

    now       = datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M")
    date_str  = now.strftime("%Y-%m-%d")
    time_str  = now.strftime("%H-%M")

    # Build top scorers list
    top_buys  = [s for s in signals if s.get("action","").startswith("BUY")]
    top_watch = [s for s in signals if s.get("action","").startswith("WATCH")]
    top_exits = [s for s in signals if s.get("action","").startswith("CLOSE")]

    payload = {
        "meta": {
            "timestamp":   timestamp,
            "cycle_type":  cycle_type,
            "machine":     MACHINE_ID,
            "dry_run":     dry_run,
        },
        "summary": {
            "tickers_scanned": len(signals),
            "entries":         entries,
            "exits":           exits,
            "on_watch":        len(top_watch),
            "portfolio_value": account.get("portfolio_value", 0),
            "cash":            account.get("cash", 0),
            "buying_power":    account.get("buying_power", 0),
        },
        "trades": {
            "buys":  [{"ticker": s["ticker"], "score": s["score"],
                       "price":  s["risk"].get("close",""),
                       "stop":   s["risk"].get("stop_2x_atr",""),
                       "target": s["risk"].get("target_2r","")}
                      for s in top_buys],
            "closes": [{"ticker": s["ticker"], "score": s["score"],
                        "reason": s["action"]}
                       for s in top_exits],
        },
        "watch_list": [{"ticker": s["ticker"], "score": s["score"],
                        "price":  s["risk"].get("close","")}
                       for s in top_watch[:20]],  # top 20 watch tickers
        "open_positions": positions,
        "top_signals":    sorted(
            [{"ticker": s["ticker"], "score": s["score"],
              "action": s["action"], "price": s["risk"].get("close","")}
             for s in signals],
            key=lambda x: x["score"], reverse=True
        )[:30],  # top 30 by score
        "errors": errors or [],
    }

    # Push cycle log
    path    = f"logs/{date_str}_{time_str}_{cycle_type}.json"
    message = f"[{MACHINE_ID}] {cycle_type} cycle — {entries} buys, {exits} exits, {len(top_watch)} watching"
    ok = _push_file(path, payload, message)

    # Always overwrite latest.json for quick status check
    _push_file("summary/latest.json", payload,
               f"[{MACHINE_ID}] latest cycle update {timestamp}")

    # Update daily summary
    _push_daily_summary(date_str, payload)

    if ok:
        print(f"  [logger] Cycle logged to github.com/{GITHUB_REPO}/blob/main/{path}")

    return ok


def log_error(source: str, error: str, context: dict = None) -> bool:
    """Log an error to GitHub."""
    now      = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H-%M")

    payload = {
        "timestamp": now.strftime("%Y-%m-%d %H:%M"),
        "machine":   MACHINE_ID,
        "source":    source,
        "error":     str(error),
        "context":   context or {},
    }

    path    = f"errors/{date_str}_{time_str}_{source}.json"
    message = f"[{MACHINE_ID}] ERROR in {source}: {str(error)[:60]}"
    ok = _push_file(path, payload, message)

    if ok:
        print(f"  [logger] Error logged to github.com/{GITHUB_REPO}")

    return ok


def log_portfolio_snapshot(account: dict, positions: dict) -> bool:
    """Push a daily portfolio snapshot."""
    now      = datetime.now()
    date_str = now.strftime("%Y-%m-%d")

    payload = {
        "timestamp":  now.strftime("%Y-%m-%d %H:%M"),
        "machine":    MACHINE_ID,
        "account":    account,
        "positions":  positions,
        "position_count": len(positions),
    }

    path    = f"portfolio/{date_str}_snapshot.json"
    message = f"[{MACHINE_ID}] portfolio snapshot — ${account.get('portfolio_value',0):,.2f}"
    return _push_file(path, payload, message)


def _push_daily_summary(date_str: str, cycle_payload: dict) -> bool:
    """Append to or create a daily summary file."""
    path = f"summary/{date_str}_daily.json"

    # Try to read existing daily summary
    existing_cycles = []
    try:
        url = f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{path}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json",
            }
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data     = json.loads(resp.read())
            existing = json.loads(base64.b64decode(data["content"]).decode())
            existing_cycles = existing.get("cycles", [])
    except Exception:
        pass

    # Append this cycle's summary
    existing_cycles.append({
        "time":            cycle_payload["meta"]["timestamp"],
        "cycle_type":      cycle_payload["meta"]["cycle_type"],
        "entries":         cycle_payload["summary"]["entries"],
        "exits":           cycle_payload["summary"]["exits"],
        "portfolio_value": cycle_payload["summary"]["portfolio_value"],
        "tickers_scanned": cycle_payload["summary"]["tickers_scanned"],
    })

    daily = {
        "date":            date_str,
        "machine":         MACHINE_ID,
        "cycles":          existing_cycles,
        "final_portfolio": cycle_payload["summary"]["portfolio_value"],
        "total_entries":   sum(c["entries"] for c in existing_cycles),
        "total_exits":     sum(c["exits"] for c in existing_cycles),
    }

    return _push_file(path, daily, f"[{MACHINE_ID}] daily summary update {date_str}")


# ─────────────────────────────────────────────
# README INITIALIZER
# ─────────────────────────────────────────────

def init_repo() -> bool:
    """
    Push a README to the repo on first run.
    Safe to call multiple times — only creates if missing.
    """
    readme = {
        "readme": True,
        "description": "TKC Studio Stock AI — Trade Logs",
        "structure": {
            "logs/":      "Per-cycle trade activity (buys, closes, signals)",
            "portfolio/": "Daily portfolio snapshots",
            "errors/":    "Any errors caught during cycles",
            "summary/":   "latest.json = most recent cycle, YYYY-MM-DD_daily.json = daily rollup",
        },
        "machines": {
            "primary":  "Tim's machine",
            "dads-pc":  "Dad's machine",
        }
    }
    return _push_file("README.json", readme, "init: TKC trader log repo")
