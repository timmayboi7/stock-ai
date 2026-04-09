@echo off
cd /d "%~dp0"
echo [%date% %time%] Running stock trader cycle (full S^&P500 + Nasdaq scan)...
python paper_trader.py
echo [%date% %time%] Running crypto trader cycle (full crypto universe scan)...
python crypto_trader.py
echo [%date% %time%] Cycles complete.
