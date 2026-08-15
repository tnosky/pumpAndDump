@echo off
python -m pytest -q
if errorlevel 1 pause
