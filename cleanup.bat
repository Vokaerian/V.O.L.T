@echo off
cd /d "%~dp0"
node tools\cleanup.js %*
pause
