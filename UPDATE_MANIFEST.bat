@echo off
cd /d "%~dp0"
python scripts/update_archive_manifest.py
if errorlevel 1 pause
