@echo off
setlocal
cd /d "%~dp0" || exit /b 1

if not exist ".local\pgdata\PG_VERSION" goto missing
if not exist ".local\pgsql\bin\pg_ctl.exe" goto missing
if not exist ".local\clean-venv\Scripts\reconcile.exe" goto missing

".local\pgsql\bin\pg_ctl.exe" status -D .local\pgdata >nul 2>&1
if errorlevel 1 (
    echo Starting the local demo database...
    ".local\pgsql\bin\pg_ctl.exe" -D .local\pgdata -l .local\postgres.log -o "-h 127.0.0.1 -p 55432" -w start
    if errorlevel 1 exit /b 1
)

set "RECON_DATABASE_URL=postgresql+psycopg://recon_local@127.0.0.1:55432/recon_final"
".local\clean-venv\Scripts\reconcile.exe" dashboard --local-demo --open-browser
exit /b %errorlevel%

:missing
echo This shortcut needs the portable demo already installed in .local. See README.md for setup.
exit /b 1
