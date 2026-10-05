@echo off
cd /d "%~dp0"
python bot.py --setup || py bot.py --setup
pause
