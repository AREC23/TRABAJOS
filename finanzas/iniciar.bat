@echo off
cd /d "%~dp0"
python server.py || py server.py
pause
