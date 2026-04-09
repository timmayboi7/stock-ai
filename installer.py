"""
TKC Studio Stock AI — Installer
Professional setup wizard. Handles everything from scratch.
"""

import os
import sys
import subprocess
import urllib.request
import shutil
import time
import json
import re
import tempfile
import platform
import webbrowser
from pathlib import Path

# ── Bootstrap rich ────────────────────────────────────────────────────
def bootstrap_rich():
    try:
        import rich
    except ImportError:
        print("Setting up installer display... please wait.")
        subprocess.run([sys.executable, "-m", "pip", "install", "rich", "-q"],
                       capture_output=True)
bootstrap_rich()

from rich.console import Console
from rich.panel import Panel
from rich.progress import (Progress, SpinnerColumn, BarColumn,
                           TextColumn, TimeElapsedColumn, DownloadColumn,
                           TransferSpeedColumn)
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.align import Align
from rich.rule import Rule
from rich.columns import Columns
from rich import box

console = Console()

INSTALL_DIR  = Path(os.path.dirname(os.path.abspath(__file__)))
PYTHON_URL   = "https://www.python.org/ftp/python/3.12.0/python-3.12.0-amd64.exe"
OLLAMA_URL   = "https://ollama.com/download/OllamaSetup.exe"

PIP_PACKAGES = [
    "yfinance", "ta", "pandas", "anthropic", "openai",
    "streamlit", "plotly", "backtrader",
    "alpaca-py", "python-dotenv", "requests",
    "lxml", "html5lib", "rich",
]


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def run(cmd, shell=True):
    return subprocess.run(cmd, shell=shell, capture_output=True, text=True)

def run_visible(cmd):
    return subprocess.run(cmd, shell=True)

def success(msg): console.print(f"  [bold green]✓[/bold green]  {msg}")
def warn(msg):
    from rich.markup import escape
    console.print(f"  [bold yellow]⚠[/bold yellow]  {escape(str(msg))}")
def error(msg):
    from rich.markup import escape
    console.print(f"  [bold red]✗[/bold red]  {escape(str(msg))}")
def info(msg):
    from rich.markup import escape
    console.print(f"  [dim cyan]→[/dim cyan]  {escape(str(msg))}")
def blank():      console.print()

def section(title: str):
    blank()
    console.rule(f"[bold cyan]{title}[/bold cyan]")
    blank()

def pause(msg="Press Enter to continue..."):
    console.print(f"\n  [dim]{msg}[/dim]")
    input()

def download_file(url: str, dest: Path, label: str) -> bool:
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn(f"  [cyan]{label}[/cyan]"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeElapsedColumn(),
            console=console, transient=True,
        ) as progress:
            task = progress.add_task("", total=None)
            def update(block, block_size, total_size):
                if total_size > 0:
                    progress.update(task, total=total_size,
                                    completed=block * block_size)
            urllib.request.urlretrieve(url, dest, reporthook=update)
        return True
    except Exception as e:
        error(f"Download failed: {e}")
        return False


# ─────────────────────────────────────────────
# SCREEN 1 — WELCOME
# ─────────────────────────────────────────────

def show_welcome():
    console.clear()
    blank()
    console.print(Align.center(Panel(
        Align.center(Text.from_markup(
            "[bold cyan]TKC Studio Stock AI[/bold cyan]\n"
            "[dim]Setup Wizard — Version 1.0[/dim]\n\n"
            "[white]Automated stock & crypto trading powered by AI[/white]\n\n"
            "[dim]This wizard will set up everything on your computer.\n"
            "You do [bold]not[/bold] need any technical knowledge.\n"
            "Just follow the steps — it takes about 10–20 minutes.[/dim]"
        )),
        border_style="cyan", padding=(1, 6), width=64,
    )))
    blank()

    console.print(Align.center(Panel(
        Text.from_markup(
            "[bold white]What this app does:[/bold white]\n\n"
            "  [cyan]•[/cyan]  Scans hundreds of stocks and crypto every day\n"
            "  [cyan]•[/cyan]  Uses AI to explain each stock in plain English\n"
            "  [cyan]•[/cyan]  Tells you what to buy, wait on, or avoid\n"
            "  [cyan]•[/cyan]  Practices trading automatically with [bold green]fake money[/bold green]\n"
            "       so you can learn with zero financial risk\n"
            "  [cyan]•[/cyan]  Runs 3 times a day by itself — no action needed"
        ),
        border_style="dim", padding=(0, 4), width=64,
    )))
    blank()
    pause("Press Enter to begin setup...")


# ─────────────────────────────────────────────
# SCREEN 2 — SYSTEM SCAN
# ─────────────────────────────────────────────

def scan_hardware() -> dict:
    section("Step 1 of 7 — Scanning Your Computer")

    info("Checking your hardware... this takes a few seconds.")
    blank()

    hw = {
        "cpu_name":   "Unknown",
        "cpu_cores":  os.cpu_count() or 2,
        "ram_gb":     0.0,
        "disk_free_gb": 0.0,
        "gpu_name":   "None detected",
        "vram_gb":    0.0,
        "is_nvidia":  False,
        "is_amd":     False,
        "python_ok":  False,
        "python_ver": "",
        "ollama_ok":  False,
    }

    # CPU
    try:
        r = run("wmic cpu get Name /format:list")
        for line in r.stdout.splitlines():
            if line.startswith("Name="):
                name = line.split("=",1)[1].strip()
                if name:
                    hw["cpu_name"] = name
                    break
    except Exception:
        pass
    if hw["cpu_name"] == "Unknown":
        try:
            r = run('powershell -Command "(Get-CimInstance Win32_Processor).Name"')
            name = r.stdout.strip()
            if name:
                hw["cpu_name"] = name
        except Exception:
            hw["cpu_name"] = platform.processor() or f"CPU ({hw['cpu_cores']} cores)"

    # RAM — try multiple methods
    try:
        r = run("wmic computersystem get TotalPhysicalMemory /format:list")
        for line in r.stdout.splitlines():
            if line.startswith("TotalPhysicalMemory="):
                val = line.split("=",1)[1].strip()
                if val.isdigit():
                    hw["ram_gb"] = int(val) / (1024**3)
                    break
    except Exception:
        pass
    if hw["ram_gb"] == 0:
        try:
            # PowerShell fallback
            r = run('powershell -Command "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"')
            val = r.stdout.strip()
            if val.isdigit():
                hw["ram_gb"] = int(val) / (1024**3)
        except Exception:
            pass
    if hw["ram_gb"] == 0:
        # Last resort — assume 8GB so installer doesn't block
        hw["ram_gb"] = 8.0

    # Disk
    try:
        total, used, free = shutil.disk_usage(INSTALL_DIR)
        hw["disk_free_gb"] = free / (1024**3)
    except Exception:
        pass

    # GPU via PowerShell
    try:
        r = run('powershell -Command "Get-WmiObject Win32_VideoController | Select-Object Name,AdapterRAM | ConvertTo-Json"')
        if r.returncode == 0 and r.stdout.strip():
            raw = r.stdout.strip()
            gpus = json.loads(raw) if raw.startswith("[") else [json.loads(raw)]
            for gpu in gpus:
                name   = str(gpu.get("Name","")).strip()
                vram_b = gpu.get("AdapterRAM", 0) or 0
                vram   = vram_b / (1024**3)
                if vram > hw["vram_gb"] or hw["gpu_name"] == "None detected":
                    hw["gpu_name"]  = name
                    hw["vram_gb"]   = round(vram, 1)
                    hw["is_nvidia"] = any(x in name.lower() for x in ["nvidia","geforce","rtx","gtx","quadro"])
                    hw["is_amd"]    = any(x in name.lower() for x in ["amd","radeon","rx "])
    except Exception:
        pass

    # Python
    ver = sys.version_info
    hw["python_ok"]  = ver >= (3, 10)
    hw["python_ver"] = f"{ver.major}.{ver.minor}.{ver.micro}"

    # Ollama
    r = run("ollama --version")
    hw["ollama_ok"] = r.returncode == 0
    if hw["ollama_ok"]:
        hw["ollama_model_ready"] = False
        r2 = run("ollama list")
        if "llama" in r2.stdout.lower():
            hw["ollama_model_ready"] = True

    # ── Display results ───────────────────────────────────────────────
    table = Table(box=box.ROUNDED, border_style="dim", width=62)
    table.add_column("Component",    style="cyan",  width=22)
    table.add_column("Found",        width=28)
    table.add_column("Status",       width=10)

    # CPU
    cpu_short = hw["cpu_name"][:26] + "…" if len(hw["cpu_name"]) > 26 else hw["cpu_name"]
    table.add_row("Processor", f"{cpu_short} ({hw['cpu_cores']} cores)",
                  "[green]✓[/green]")

    # RAM
    ram_status = "[green]✓[/green]" if hw["ram_gb"] >= 8 else "[yellow]⚠ Low[/yellow]"
    table.add_row("Memory (RAM)", f"{hw['ram_gb']:.1f} GB", ram_status)

    # Disk
    disk_status = "[green]✓[/green]" if hw["disk_free_gb"] >= 10 else "[yellow]⚠ Low[/yellow]"
    table.add_row("Free Disk Space", f"{hw['disk_free_gb']:.1f} GB available", disk_status)

    # GPU
    if hw["gpu_name"] != "None detected":
        gpu_short = hw["gpu_name"][:26] + "…" if len(hw["gpu_name"]) > 26 else hw["gpu_name"]
        vram_str  = f"{hw['vram_gb']:.1f} GB VRAM" if hw["vram_gb"] > 0 else "VRAM unknown"
        gpu_status = "[green]✓[/green]" if hw["vram_gb"] >= 3 else "[yellow]Limited[/yellow]"
        table.add_row("Graphics Card", f"{gpu_short} / {vram_str}", gpu_status)
    else:
        table.add_row("Graphics Card", "None / integrated", "[yellow]CPU only[/yellow]")

    # Python
    py_status = "[green]✓ Ready[/green]" if hw["python_ok"] else "[red]✗ Will install[/red]"
    table.add_row("Python",  hw["python_ver"], py_status)

    # Ollama
    ol_status = "[green]✓ Installed[/green]" if hw["ollama_ok"] else "[dim]Not yet[/dim]"
    table.add_row("Ollama AI Engine", "Installed" if hw["ollama_ok"] else "Not installed", ol_status)

    console.print(table)
    blank()

    # Warnings
    if hw["ram_gb"] < 8 and hw["ram_gb"] > 0:
        warn(f"Only {hw['ram_gb']:.1f} GB RAM detected. The app works but may be slow. 8GB+ recommended.")
    if hw["disk_free_gb"] < 10:
        warn(f"Only {hw['disk_free_gb']:.1f} GB free disk space. You need at least 6 GB for the AI model.")
    if hw["disk_free_gb"] < 6:
        error("Not enough disk space to continue. Please free up at least 6 GB and rerun this installer.")
        pause("Press Enter to exit...")
        sys.exit(1)

    success("System scan complete.")
    pause()
    return hw


# ─────────────────────────────────────────────
# SCREEN 3 — PYTHON
# ─────────────────────────────────────────────

def ensure_python(hw: dict):
    if hw["python_ok"]:
        return

    section("Step 2 of 7 — Installing Python")

    console.print(Panel(
        "[white]Python is the programming language this app runs on.\n"
        "It needs to be installed — this happens automatically.[/white]\n\n"
        "[dim]Download size: ~25 MB. Takes about 2 minutes.[/dim]",
        border_style="dim", padding=(0,2),
    ))
    blank()

    tmp = Path(tempfile.gettempdir()) / "python_installer.exe"
    if not download_file(PYTHON_URL, tmp, "Downloading Python 3.12"):
        error("Could not download Python. Check your internet connection.")
        pause("Press Enter to exit..."); sys.exit(1)

    info("Installing Python... (a security prompt may appear — click Yes)")
    run_visible(f'"{tmp}" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0')
    time.sleep(2)

    success("Python installed.")
    warn("Please close this window and double-click INSTALL.bat again to continue.")
    pause("Press Enter to exit...")
    sys.exit(0)


# ─────────────────────────────────────────────
# SCREEN 4 — LLM SELECTION
# ─────────────────────────────────────────────

def get_llm_options(hw: dict) -> list[dict]:
    vram      = hw["vram_gb"]
    ram       = hw["ram_gb"]
    is_nvidia = hw["is_nvidia"]
    is_amd    = hw["is_amd"]
    has_gpu   = vram >= 3

    options = []

    if has_gpu and vram >= 6:
        options.append({
            "id": "ollama_8b",
            "label": "Llama 3.1 8B  —  Local AI (Best Free Option)",
            "provider": "Ollama (free, runs on your computer)",
            "model": "llama3.1:8b",
            "cost": "Completely FREE — no ongoing charges",
            "quality": "★★★★☆  Very good analysis",
            "speed": "Fast  (~5–10 seconds per stock)" if is_nvidia else "Medium  (~15–25s per stock)",
            "download_gb": 4.7,
            "needs_key": False,
            "recommended": True,
            "why": f"Your {hw['gpu_name']} has enough memory to run this well.",
        })

    if has_gpu and vram >= 3:
        options.append({
            "id": "ollama_3b",
            "label": "Llama 3.2 3B  —  Local AI (Lightweight)",
            "provider": "Ollama (free, runs on your computer)",
            "model": "llama3.2:3b",
            "cost": "Completely FREE — no ongoing charges",
            "quality": "★★★☆☆  Good analysis",
            "speed": "Very fast  (~3–8 seconds per stock)",
            "download_gb": 2.0,
            "needs_key": False,
            "recommended": vram < 6,
            "why": f"Smaller model, fits comfortably in your {vram:.0f}GB GPU memory.",
        })

    if ram >= 8:
        options.append({
            "id": "ollama_cpu",
            "label": "Llama 3.2 3B  —  Local AI (CPU, no GPU needed)",
            "provider": "Ollama (free, runs on your computer)",
            "model": "llama3.2:3b",
            "cost": "Completely FREE — no ongoing charges",
            "quality": "★★★☆☆  Good analysis",
            "speed": "Slow  (~20–40 seconds per stock)",
            "download_gb": 2.0,
            "needs_key": False,
            "recommended": not has_gpu,
            "why": "Works without a GPU. Slower but free.",
        })

    options.append({
        "id": "anthropic",
        "label": "Claude Haiku  —  Cloud AI (Highest Quality)",
        "provider": "Anthropic  (cloud service, requires account)",
        "model": "claude-haiku-4-5-20251001",
        "cost": "~$0.001 per stock  (~$1–3 per month for typical use)",
        "cost_detail": (
            "Example: scanning 10 stocks, 3 times a day\n"
            "= 30 AI calls/day × $0.001 = $0.03/day = ~$1/month\n"
            "You add credit in advance — no surprise bills."
        ),
        "quality": "★★★★★  Best analysis quality",
        "speed": "Very fast  (~2–3 seconds per stock)",
        "download_gb": 0,
        "needs_key": True,
        "key_url": "https://console.anthropic.com",
        "signup_url": "https://console.anthropic.com",
        "recommended": False,
        "why": "Best quality AI analysis. Small cost. Good for serious traders.",
    })

    options.append({
        "id": "openai",
        "label": "GPT-4o Mini  —  Cloud AI (OpenAI)",
        "provider": "OpenAI  (cloud service, requires account)",
        "model": "gpt-4o-mini",
        "cost": "~$0.0006 per stock  (~$0.50–1.50 per month for typical use)",
        "cost_detail": (
            "Example: scanning 10 stocks, 3 times a day\n"
            "= 30 AI calls/day × $0.0006 = $0.018/day = ~$0.55/month\n"
            "Pay-as-you-go with a preset spending limit."
        ),
        "quality": "★★★★☆  Very good analysis",
        "speed": "Fast  (~3–5 seconds per stock)",
        "download_gb": 0,
        "needs_key": True,
        "key_url": "https://platform.openai.com/api-keys",
        "signup_url": "https://platform.openai.com/signup",
        "recommended": False,
        "why": "Good quality, slightly cheaper than Claude.",
    })

    return options


def select_llm(hw: dict) -> dict:
    section("Step 3 of 7 — Choose Your AI")

    console.print(Panel(
        "[white]The app uses an AI to analyze stocks and give you plain-English\n"
        "recommendations. You need to choose which AI to use.\n\n"
        "[bold]Local AI[/bold] runs entirely on [cyan]your computer[/cyan] — free, private, no account needed.\n"
        "[bold]Cloud AI[/bold] uses an [cyan]online service[/cyan] — faster and smarter, small monthly cost.[/bold][/white]",
        border_style="dim", padding=(0,2),
    ))
    blank()

    options = get_llm_options(hw)

    # Display options table
    table = Table(box=box.ROUNDED, border_style="dim", width=72, show_lines=True)
    table.add_column("#",        width=3,  style="cyan bold", justify="center")
    table.add_column("Option",   width=40)
    table.add_column("Cost",     width=14)
    table.add_column("Speed",    width=10)

    for i, opt in enumerate(options, 1):
        from rich.markup import escape
        rec_tag = " [bold green](Recommended)[/bold green]" if opt.get("recommended") else ""
        label   = escape(opt["label"])
        prov    = escape(opt["provider"])
        name    = f"[white]{label}[/white]{rec_tag}\n[dim]{prov}[/dim]"
        cost    = escape(opt["cost"][:13])
        speed   = escape(opt["speed"][:9])
        table.add_row(str(i), name, cost, speed)

    console.print(table)
    blank()

    # Ask for selection
    default = next((i+1 for i,o in enumerate(options) if o.get("recommended")), 1)
    while True:
        try:
            choice = IntPrompt.ask(
                f"  [cyan]Enter the number of your choice[/cyan] (1–{len(options)})",
                default=default
            )
            if 1 <= choice <= len(options):
                break
            warn(f"Please enter a number between 1 and {len(options)}")
        except Exception:
            warn("Please enter a valid number")

    selected = options[choice - 1]
    blank()

    # Show detail panel for selected option
    from rich.markup import escape
    detail_lines = [
        f"[bold white]{escape(selected['label'])}[/bold white]\n",
        f"[cyan]Quality:[/cyan]  {escape(selected['quality'])}",
        f"[cyan]Speed:[/cyan]    {escape(selected['speed'])}",
        f"[cyan]Cost:[/cyan]     {escape(selected['cost'])}",
    ]
    if selected.get("cost_detail"):
        detail_lines.append(f"\n[dim]{escape(selected['cost_detail'])}[/dim]")
    if selected.get("download_gb") and selected["download_gb"] > 0:
        detail_lines.append(f"\n[yellow]Note:[/yellow] Requires a [bold]{selected['download_gb']} GB[/bold] one-time download.")
    detail_lines.append(f"\n[dim]{escape(selected['why'])}[/dim]")

    console.print(Panel(
        "\n".join(detail_lines),
        border_style="cyan", padding=(0,2),
    ))
    blank()

    confirm = Confirm.ask("  Proceed with this choice?", default=True)
    if not confirm:
        return select_llm(hw)

    return selected


# ─────────────────────────────────────────────
# SCREEN 5 — GET API KEY (if cloud)
# ─────────────────────────────────────────────

def setup_llm_key(llm: dict) -> str:
    if not llm["needs_key"]:
        return ""

    section(f"Step 4 of 7 — {llm['provider'].split('(')[0].strip()} API Key")

    is_anthropic = llm["id"] == "anthropic"
    provider     = "Anthropic" if is_anthropic else "OpenAI"
    signup_url   = llm["signup_url"]
    key_url      = llm["key_url"]
    key_prefix   = "sk-ant" if is_anthropic else "sk-"

    console.print(Panel(
        f"[bold white]You need a free {provider} account and an API key.[/bold white]\n\n"
        f"[bold]What is an API key?[/bold]\n"
        f"It's a password that lets this app connect to {provider}'s AI.\n"
        f"Think of it like a library card — it identifies your account.\n\n"
        f"[bold]Cost estimate:[/bold]\n"
        f"{llm['cost']}\n"
        f"{llm.get('cost_detail','')}\n\n"
        f"[dim]You set a spending limit so you can never be charged more than you allow.\n"
        f"Most users spend less than $2/month.[/dim]",
        border_style="cyan", padding=(0,2),
    ))
    blank()

    console.print(f"  [bold]Follow these steps to get your {provider} API key:[/bold]")
    blank()

    if is_anthropic:
        steps = [
            f"Go to [cyan underline]{signup_url}[/cyan underline]",
            "Click [bold]Sign Up[/bold] and create a free account",
            "Once logged in, click [bold]Billing[/bold] in the left menu",
            "Click [bold]Add Credits[/bold] — start with $5 (plenty for months of use)",
            "Then click [bold]API Keys[/bold] in the left menu",
            "Click [bold]Create Key[/bold] — give it any name you like",
            "Copy the key that appears (starts with [cyan]sk-ant[/cyan])",
            "Come back here and paste it below",
        ]
    else:
        steps = [
            f"Go to [cyan underline]{signup_url}[/cyan underline]",
            "Click [bold]Sign Up[/bold] and create a free account",
            "Once logged in, go to [bold]Billing[/bold] and add $5 credit",
            "Set a [bold]spending limit[/bold] of $5/month for safety",
            f"Go to [cyan underline]{key_url}[/cyan underline]",
            "Click [bold]Create new secret key[/bold]",
            "Copy the key (starts with [cyan]sk-[/cyan])",
            "Come back here and paste it below",
        ]

    step_table = Table(box=box.SIMPLE, show_header=False, padding=(0,2))
    step_table.add_column("N", style="cyan bold", width=4)
    step_table.add_column("Action")
    for i, step in enumerate(steps, 1):
        step_table.add_row(f"{i}.", step)
    console.print(step_table)
    blank()

    open_browser = Confirm.ask(f"  Open {provider}'s website in your browser now?", default=True)
    if open_browser:
        webbrowser.open(signup_url)
        blank()
        info("Browser opened. Complete the steps above, then come back here.")
        pause("Press Enter when you have your API key ready...")

    blank()
    api_key = ""
    while not api_key.startswith(key_prefix):
        api_key = Prompt.ask(
            f"  [cyan]Paste your {provider} API key here[/cyan]"
        ).strip()
        if not api_key.startswith(key_prefix):
            warn(f"{provider} API keys start with '{key_prefix}' — that doesn't look right. Try again.")

    success(f"{provider} API key accepted.")
    return api_key


# ─────────────────────────────────────────────
# SCREEN 6 — OLLAMA INSTALL + MODEL PULL
# ─────────────────────────────────────────────

def setup_ollama(hw: dict, llm: dict):
    if llm["needs_key"]:
        return   # Cloud LLM — no Ollama needed

    # Install Ollama if missing
    if not hw["ollama_ok"]:
        section("Step 4 of 7 — Installing Local AI Engine (Ollama)")

        console.print(Panel(
            "[white]Ollama is a free program that runs AI on your computer.\n"
            "Your data [bold]never leaves your machine[/bold] — everything is private.\n\n"
            "[dim]Download size: ~120 MB. Takes about 1–2 minutes.[/dim][/white]",
            border_style="dim", padding=(0,2),
        ))
        blank()

        tmp = Path(tempfile.gettempdir()) / "OllamaSetup.exe"
        if not download_file(OLLAMA_URL, tmp, "Downloading Ollama"):
            warn("Could not download Ollama automatically.")
            info("Please download it manually from [cyan underline]https://ollama.com[/cyan underline]")
            info("Then rerun this installer.")
            pause("Press Enter to exit..."); sys.exit(1)

        info("Installing Ollama... (a security prompt may appear — click Yes)")
        run_visible(f'"{tmp}" /S')
        time.sleep(4)

        # Add to path for this session
        ollama_path = Path(os.environ.get("LOCALAPPDATA","")) / "Programs" / "Ollama"
        if ollama_path.exists():
            os.environ["PATH"] += f";{ollama_path}"

        success("Ollama installed.")

    # Pull the model
    model      = llm["model"]
    size_gb    = llm["download_gb"]
    model_name = model.split(":")[0]

    # Check if already pulled
    r = run("ollama list")
    if model_name in r.stdout.lower():
        success(f"AI model {model} already downloaded — skipping.")
        return

    section(f"Step 5 of 7 — Downloading AI Model")

    console.print(Panel(
        f"[white]Downloading [cyan]{model}[/cyan]\n\n"
        f"[bold]Size:[/bold] approximately [bold]{size_gb} GB[/bold]\n"
        f"[bold]Time:[/bold] depends on your internet speed\n"
        f"  •  Fast internet (100 Mbps+): ~5 minutes\n"
        f"  •  Average internet (25 Mbps): ~15–20 minutes\n"
        f"  •  Slow internet (10 Mbps): ~30–40 minutes\n\n"
        f"[dim]This is a one-time download. The model stays on your computer.[/dim][/white]",
        border_style="dim", padding=(0,2),
    ))
    blank()
    info("Starting download... you'll see progress below.")
    blank()

    with Progress(
        SpinnerColumn(),
        TextColumn(f"  [cyan]Pulling {model}...[/cyan]"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("", total=100)

        # Start ollama serve first
        subprocess.Popen("ollama serve", shell=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)

        process = subprocess.Popen(
            f"ollama pull {model}",
            shell=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True,
        )
        for line in process.stdout:
            line = line.strip()
            if "%" in line:
                try:
                    pct = float(re.search(r"(\d+\.?\d*)%", line).group(1))
                    progress.update(task, completed=pct)
                except Exception:
                    pass
            if "success" in line.lower():
                progress.update(task, completed=100)
        process.wait()

    if process.returncode == 0:
        success(f"{model} downloaded and ready.")
    else:
        warn("Model download may have encountered issues.")
        info("If the app doesn't work, open Command Prompt and run:")
        info(f"  ollama pull {model}")


# ─────────────────────────────────────────────
# SCREEN 7 — INSTALL PYTHON PACKAGES
# ─────────────────────────────────────────────

def install_packages():
    section("Step 5 of 7 — Installing App Components")

    info(f"Installing {len(PIP_PACKAGES)} required components...")
    blank()

    with Progress(
        SpinnerColumn(),
        TextColumn("  [cyan]{task.description}[/cyan]"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task   = progress.add_task("Starting...", total=len(PIP_PACKAGES))
        failed = []
        for pkg in PIP_PACKAGES:
            progress.update(task, description=f"Installing {pkg}...")
            r = run(f'"{sys.executable}" -m pip install {pkg} -q --exists-action i')
            if r.returncode != 0:
                failed.append(pkg)
            progress.advance(task)

    blank()
    if not failed:
        success(f"All {len(PIP_PACKAGES)} components installed successfully.")
    else:
        warn(f"Some components had issues: {', '.join(failed)}")
        info("The app may still work. If you see errors, contact Tim.")


# ─────────────────────────────────────────────
# SCREEN 8 — ALPACA SETUP
# ─────────────────────────────────────────────

def setup_alpaca() -> tuple[str, str]:
    section("Step 6 of 7 — Practice Trading Account (Alpaca)")

    console.print(Panel(
        "[bold white]What is Alpaca?[/bold white]\n\n"
        "Alpaca is a [bold]completely free[/bold] trading platform used by developers\n"
        "and investors. This app uses Alpaca's [bold green]Paper Trading[/bold green] feature,\n"
        "which lets you practice with [bold green]$100,000 in fake money[/bold green].\n\n"
        "[bold]You will never risk real money[/bold] — this is purely for learning\n"
        "and testing how the AI's recommendations perform.\n\n"
        "[dim]Account creation: Free. No credit card required.\n"
        "No real money is ever added or at risk.[/dim]",
        border_style="green", padding=(0,2),
    ))
    blank()

    console.print("  [bold]Here's exactly what to do — follow these steps:[/bold]")
    blank()

    steps = [
        ("Open your browser", "We'll do this for you — click Yes on the next prompt"),
        ("Go to alpaca.markets", "The website will open automatically"),
        ("Click 'Sign Up'",      "Top right corner — it's free, no credit card needed"),
        ("Fill in your details", "Name, email, password — takes 2 minutes"),
        ("Verify your email",    "Check your inbox and click the confirmation link"),
        ("Log in to your account", "Use the email and password you just created"),
        ("Find 'Paper Trading'", "Look at the TOP-LEFT dropdown — switch to Paper Trading"),
        ("Click 'API Keys'",     "In the left sidebar menu"),
        ("Click 'Generate New Key'", "A box will appear with two keys"),
        ("Copy BOTH keys",       "You'll paste them here in a moment"),
    ]

    step_table = Table(box=box.SIMPLE, show_header=False, padding=(0,2))
    step_table.add_column("N",      style="cyan bold", width=4)
    step_table.add_column("Action", style="white",     width=25)
    step_table.add_column("Detail", style="dim",       width=35)
    for i, (action, detail) in enumerate(steps, 1):
        step_table.add_row(f"{i}.", action, detail)
    console.print(step_table)
    blank()

    open_browser = Confirm.ask(
        "  Open Alpaca's website in your browser now?", default=True)
    if open_browser:
        webbrowser.open("https://alpaca.markets")
        blank()
        info("Browser opened.")
        info("Complete all 10 steps above, then come back here.")
        blank()
        console.print(Panel(
            "[yellow]⚠  Important:[/yellow]  Make sure you switch to [bold]Paper Trading[/bold]\n"
            "in the top-left dropdown before generating API keys.\n"
            "The API keys must come from Paper Trading, not Live Trading.",
            border_style="yellow", padding=(0,2),
        ))

    pause("Press Enter when you have both API keys ready...")
    blank()

    # API Key input
    console.print("  [bold]Now paste your Alpaca API keys:[/bold]")
    blank()

    info("The API Key starts with [cyan]PK[/cyan] — for example: PKxxxxxxxxxxxxxxxx")
    alpaca_key = ""
    while not alpaca_key.startswith("PK"):
        alpaca_key = Prompt.ask("  [cyan]Paste your Alpaca API Key[/cyan]").strip()
        if not alpaca_key.startswith("PK"):
            warn("That doesn't look right — Alpaca API keys start with 'PK'. Try again.")

    blank()
    info("The Secret Key is a longer string of random characters.")
    alpaca_sec = ""
    while len(alpaca_sec) < 30:
        alpaca_sec = Prompt.ask("  [cyan]Paste your Alpaca Secret Key[/cyan]").strip()
        if len(alpaca_sec) < 30:
            warn("That secret key looks too short. Make sure you copied the full key.")

    blank()
    success("Alpaca paper trading account connected!")
    info("Your paper account starts with $100,000 in simulated cash.")
    return alpaca_key, alpaca_sec


# ─────────────────────────────────────────────
# WRITE CONFIG FILES
# ─────────────────────────────────────────────

def write_configs(llm: dict, llm_key: str, alpaca_key: str, alpaca_sec: str):
    # .env file
    lines = [
        "# TKC Studio Stock AI — Configuration",
        "# Generated by installer",
        "",
        "# ── Alpaca Paper Trading ──────────────────────────────────",
        f"ALPACA_API_KEY={alpaca_key}",
        f"ALPACA_SECRET_KEY={alpaca_sec}",
        "",
        "# ── AI Backend ───────────────────────────────────────────",
    ]

    if llm["id"].startswith("ollama"):
        lines += [
            f"AI_BACKEND=ollama",
            f"OLLAMA_MODEL={llm['model']}",
            "OLLAMA_URL=http://localhost:11434",
            "",
            "# Uncomment below to use cloud AI instead:",
            "# AI_BACKEND=anthropic",
            "# ANTHROPIC_API_KEY=sk-ant-...",
        ]
    elif llm["id"] == "anthropic":
        lines += [
            "AI_BACKEND=anthropic",
            f"ANTHROPIC_API_KEY={llm_key}",
            "",
            "# Uncomment below to use free local AI instead:",
            "# AI_BACKEND=ollama",
            "# OLLAMA_MODEL=llama3.2:3b",
        ]
    elif llm["id"] == "openai":
        lines += [
            "AI_BACKEND=openai",
            f"OPENAI_API_KEY={llm_key}",
            "",
            "# Uncomment below to use free local AI instead:",
            "# AI_BACKEND=ollama",
            "# OLLAMA_MODEL=llama3.2:3b",
        ]

    # Add GitHub logging config
    lines += [
        "",
        "# ── Remote Logging (optional) ────────────────────────────────",
        "# Ask Tim for the GitHub token to enable remote log monitoring",
        "# GITHUB_TOKEN=ghp_...",
        f"GITHUB_REPO=timmayboi7/tkc-trader-logs",
        "MACHINE_ID=dads-pc",
    ]

    env_path = INSTALL_DIR / ".env"
    env_path.write_text("\n".join(lines), encoding="utf-8")
    success(".env configuration file created.")

    # config.json with default watchlists
    config = {
        "watchlist": ["NVDA", "GOOGL", "KO", "AMD", "SPY"],
        "crypto_watchlist": [
            "BTC-USD","ETH-USD","SOL-USD","BNB-USD",
            "XRP-USD","ADA-USD","AVAX-USD","DOGE-USD",
        ],
        "llm_backend": llm["id"],
    }
    config_path = INSTALL_DIR / "config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    success("App configuration saved.")


# ─────────────────────────────────────────────
# PATCH SENTIMENT.PY FOR OPENAI
# ─────────────────────────────────────────────

def patch_for_openai():
    """Add OpenAI backend support to sentiment.py if not already there."""
    sentiment_path = INSTALL_DIR / "sentiment.py"
    if not sentiment_path.exists():
        return

    content = sentiment_path.read_text(encoding="utf-8")
    if "_call_openai" in content:
        return   # Already patched

    openai_patch = '''

def _call_openai(prompt: str) -> dict | None:
    """Call OpenAI GPT-4o Mini."""
    try:
        import openai as _openai
        key = os.environ.get("OPENAI_API_KEY","")
        if not key:
            return None
        client = _openai.OpenAI(api_key=key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=MAX_TOKENS,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content
        return _parse_json(raw)
    except Exception as e:
        print(f"    [!] OpenAI error: {e}")
        return None
'''
    # Insert after _call_anthropic
    content = content.replace(
        "def call_haiku(client, prompt: str)",
        openai_patch + "\ndef call_haiku(client, prompt: str)"
    )

    # Update detect_backend to include openai
    content = content.replace(
        '    if backend in ("ollama", "anthropic"):',
        '    if backend in ("ollama", "anthropic", "openai"):'
    )
    content = content.replace(
        '    # Fall back to Anthropic\n    if os.environ.get("ANTHROPIC_API_KEY"):\n        return "anthropic"',
        '    # Fall back to Anthropic\n    if os.environ.get("ANTHROPIC_API_KEY"):\n        return "anthropic"\n\n    # Fall back to OpenAI\n    if os.environ.get("OPENAI_API_KEY"):\n        return "openai"'
    )

    # Update call_haiku to handle openai
    content = content.replace(
        '    if client is None:\n        return _call_ollama(prompt)\n    return _call_anthropic(client, prompt)',
        '    backend = os.environ.get("AI_BACKEND","").lower()\n    if backend == "openai":\n        return _call_openai(prompt)\n    if client is None:\n        return _call_ollama(prompt)\n    return _call_anthropic(client, prompt)'
    )

    sentiment_path.write_text(content, encoding="utf-8")
    success("AI backend configured for OpenAI.")


# ─────────────────────────────────────────────
# SCREEN 9 — AUTOMATION
# ─────────────────────────────────────────────

def setup_automation():
    section("Step 7 of 7 — Automatic Trading Schedule")

    console.print(Panel(
        "[bold white]How the automatic trading works:[/bold white]\n\n"
        "The app will run on its own [cyan]3 times every trading day[/cyan]:\n\n"
        "  [bold green]8:30 AM[/bold green]   Chicago time  —  Market opens, first scan\n"
        "  [bold green]11:00 AM[/bold green]  Chicago time  —  Midday check\n"
        "  [bold green]2:00 PM[/bold green]   Chicago time  —  End of day, final scan\n\n"
        "Each time it runs, it will:\n"
        "  [cyan]•[/cyan]  Check the latest signals for every stock in your watchlist\n"
        "  [cyan]•[/cyan]  Ask the AI for its analysis\n"
        "  [cyan]•[/cyan]  Place or close paper trades automatically\n\n"
        "[dim]Your computer needs to be on and connected to the internet.\n"
        "You don't need to do anything — just let it run.[/dim]",
        border_style="cyan", padding=(0,2),
    ))
    blank()

    setup = Confirm.ask("  Set up automatic trading now?", default=True)
    if not setup:
        info("Skipped — you can run setup_autotrader.ps1 later.")
        return

    bat_path = INSTALL_DIR / "run_trader.bat"
    ps_script = f"""
$folder = "{INSTALL_DIR}"
$bat    = "{bat_path}"
$action   = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$bat`"" -WorkingDirectory $folder
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)

"TKC_StockTrader_Open","TKC_StockTrader_Midday","TKC_StockTrader_Close" | ForEach-Object {{
    Unregister-ScheduledTask -TaskName $_ -Confirm:$false -ErrorAction SilentlyContinue
}}

Register-ScheduledTask -TaskName "TKC_StockTrader_Open"   -Action $action -Trigger (New-ScheduledTaskTrigger -Daily -At 8:30AM)  -Settings $settings -RunLevel Highest -Force | Out-Null
Register-ScheduledTask -TaskName "TKC_StockTrader_Midday" -Action $action -Trigger (New-ScheduledTaskTrigger -Daily -At 11:00AM) -Settings $settings -RunLevel Highest -Force | Out-Null
Register-ScheduledTask -TaskName "TKC_StockTrader_Close"  -Action $action -Trigger (New-ScheduledTaskTrigger -Daily -At 2:00PM)  -Settings $settings -RunLevel Highest -Force | Out-Null

$ollamaExe = "$env:LOCALAPPDATA\\Programs\\Ollama\\ollama.exe"
if (Test-Path $ollamaExe) {{
    Unregister-ScheduledTask -TaskName "TKC_OllamaServer" -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName "TKC_OllamaServer" `
        -Action (New-ScheduledTaskAction -Execute $ollamaExe -Argument "serve") `
        -Trigger (New-ScheduledTaskTrigger -AtStartup) `
        -Settings (New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 0)) `
        -RunLevel Highest -Force | Out-Null
}}
Write-Host "OK"
"""

    ps_tmp = Path(tempfile.gettempdir()) / "tkc_tasks.ps1"
    ps_tmp.write_text(ps_script, encoding="utf-8")

    info("Setting up scheduled tasks... (a security prompt may appear — click Yes)")
    subprocess.run(
        f'powershell -Command "Start-Process powershell -Verb RunAs -Wait '
        f'-ArgumentList \'-ExecutionPolicy Bypass -File \\\"{ps_tmp}\\\"\'"',
        shell=True, capture_output=True
    )

    check = run('powershell -Command "Get-ScheduledTask | Where-Object {$_.TaskName -like \'TKC*\'} | Measure-Object | Select-Object -ExpandProperty Count"')
    count = check.stdout.strip()
    if count and int(count.strip()) >= 3:
        success("Automatic trading scheduled — runs at 8:30 AM, 11:00 AM, 2:00 PM CT daily.")
    else:
        warn("Scheduling may not have completed fully.")
        info("If auto-trading doesn't work, run setup_autotrader.ps1 as Administrator.")


# ─────────────────────────────────────────────
# DESKTOP SHORTCUT
# ─────────────────────────────────────────────

def create_shortcut():
    launch_bat = INSTALL_DIR / "Launch Dashboard.bat"
    launch_bat.write_text(
        f'@echo off\n'
        f'title TKC Studio Stock AI\n'
        f'cd /d "{INSTALL_DIR}"\n'
        f'echo Starting AI engine...\n'
        f'start /B ollama serve >nul 2>&1\n'
        f'timeout /t 3 /nobreak >nul\n'
        f'echo Opening dashboard...\n'
        f'python -m streamlit run "{INSTALL_DIR / "dashboard.py"}"\n',
        encoding="utf-8"
    )

    placed = False
    for desktop in [
        Path(os.environ.get("USERPROFILE","")) / "Desktop",
        Path(os.environ.get("PUBLIC","C:/Users/Public")) / "Desktop",
    ]:
        try:
            if desktop.exists():
                shutil.copy(launch_bat, desktop / "TKC Stock AI.bat")
                success(f"Desktop shortcut created.")
                placed = True
                break
        except Exception:
            continue

    if not placed:
        try:
            ps = (
                f'$ws = New-Object -ComObject WScript.Shell; '
                f'$sc = $ws.CreateShortcut("$env:USERPROFILE\\Desktop\\TKC Stock AI.lnk"); '
                f'$sc.TargetPath = \\"{launch_bat}\\"; '
                f'$sc.WorkingDirectory = \\"{INSTALL_DIR}\\"; '
                f'$sc.Save()'
            )
            r = run(f'powershell -Command "{ps}"')
            if r.returncode == 0:
                success("Desktop shortcut created.")
                placed = True
        except Exception:
            pass

    if not placed:
        warn("Could not create desktop shortcut automatically.")
        info(f"To launch the app: double-click [cyan]Launch Dashboard.bat[/cyan] in the app folder.")


# ─────────────────────────────────────────────
# COMPLETE SCREEN
# ─────────────────────────────────────────────

def show_complete(llm: dict):
    blank()
    console.rule(style="green")
    blank()
    console.print(Align.center(Panel(
        Align.center(Text.from_markup(
            "[bold green]Setup Complete![/bold green]\n\n"
            "[white]TKC Studio Stock AI is installed and ready.[/white]\n\n"
            "[dim]Double-click [cyan]TKC Stock AI[/cyan] on your Desktop\n"
            "to open the dashboard in your browser.[/dim]"
        )),
        border_style="green", padding=(1,6), width=60,
    )))
    blank()

    table = Table(box=box.ROUNDED, border_style="dim", width=56)
    table.add_column("What was set up", style="cyan")
    table.add_column("Result", justify="right")
    table.add_row("System scan",          "[green]✓ Complete[/green]")
    table.add_row("Python",               "[green]✓ Ready[/green]")
    table.add_row("AI engine",            f"[green]✓ {llm['provider'].split('(')[0].strip()}[/green]")
    table.add_row("Python components",    "[green]✓ Installed[/green]")
    table.add_row("Alpaca paper trading", "[green]✓ Connected[/green]")
    table.add_row("Auto schedule",        "[green]✓ 3× daily[/green]")
    table.add_row("Desktop shortcut",     "[green]✓ Created[/green]")
    console.print(Align.center(table))
    blank()

    console.print(Align.center(Panel(
        Text.from_markup(
            "[bold white]What happens next:[/bold white]\n\n"
            "  [cyan]1.[/cyan]  Launch the app using the desktop shortcut\n"
            "  [cyan]2.[/cyan]  Click [bold]Run Scan[/bold] in the sidebar to analyze your stocks\n"
            "  [cyan]3.[/cyan]  The app will trade automatically 3× per day\n"
            "  [cyan]4.[/cyan]  Check the [bold]Paper Trade[/bold] tab to see results\n\n"
            "[dim]Run with fake money for at least 60 days before\n"
            "considering real trading.[/dim]"
        ),
        border_style="dim", padding=(0,4), width=56,
    )))
    blank()

    launch = Confirm.ask("  Launch the dashboard now?", default=True)
    if launch:
        info("Starting up...")
        subprocess.Popen("ollama serve", shell=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        subprocess.Popen(
            f'"{sys.executable}" -m streamlit run "{INSTALL_DIR / "dashboard.py"}"',
            shell=True
        )
        time.sleep(3)
        blank()
        success("Dashboard launched — your browser should open automatically.")
        info("If it doesn't, open your browser and go to: [cyan]http://localhost:8501[/cyan]")

    blank()
    pause("Press Enter to close this installer...")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    try:
        show_welcome()
        hw         = scan_hardware()
        ensure_python(hw)
        llm        = select_llm(hw)
        llm_key    = setup_llm_key(llm)
        setup_ollama(hw, llm)
        install_packages()
        alpaca_key, alpaca_sec = setup_alpaca()
        write_configs(llm, llm_key, alpaca_key, alpaca_sec)
        if llm["id"] == "openai":
            patch_for_openai()
        setup_automation()
        create_shortcut()
        show_complete(llm)

    except KeyboardInterrupt:
        blank(); blank()
        warn("Setup cancelled.")
        blank()
        sys.exit(0)

    except Exception as e:
        blank()
        from rich.markup import escape
        console.print(f"  [bold red]✗[/bold red]  An unexpected error occurred: {escape(str(e))}")
        blank()
        console.print("[dim]Please take a photo of this screen and send it to Tim.[/dim]")
        blank()
        pause("Press Enter to exit...")
        sys.exit(1)


if __name__ == "__main__":
    import traceback
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        log_path = INSTALL_DIR / "installer_error.log"
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        print(f"\nFATAL ERROR: {e}")
        print(f"Full details saved to: {log_path}")
        print("\n" + traceback.format_exc())
        input("Press Enter to exit...")
