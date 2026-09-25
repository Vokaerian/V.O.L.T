@echo off
rem RWJSC dev launcher: double-click to start the app in dev mode
rem (Vite dev server + Electron window, hot-reloading on edit).
setlocal
cd /d "%~dp0src" || goto :nosrc

where node >nul 2>nul || goto :nonode

rem Always install: a no-op when package-lock already matches package.json.
call npm install || goto :failed

call npm run dev || goto :failed
goto :end

:nosrc
echo Could not find the src folder next to dev.bat.
goto :end

:nonode
echo Node.js was not found on PATH. Install Node.js 20.19 or newer from https://nodejs.org and try again.
goto :end

:failed
echo.
echo RWJSC dev session exited with an error (see above).

:end
echo.
pause
