@echo off
REM SAWSUBE — Windows start script
setlocal enabledelayedexpansion

cd /d "%~dp0"

if not exist .venv (
  echo Creating venv...
  python -m venv .venv || goto :error
)

call .venv\Scripts\activate.bat

echo Installing backend deps...
python -m pip install --upgrade pip >nul
pip install -r backend\requirements.txt || goto :error

if not exist .env (
  copy .env.example .env >nul
  echo Created .env from template — edit and re-run if needed.
)

REM Build frontend if Node available and no dist
where node >nul 2>nul
if %errorlevel%==0 (
  if not exist frontend\dist (
    echo Building frontend...
    pushd frontend
    call npm install || goto :error
    call npm run build || goto :error
    popd
  )
) else (
  echo Node.js not found — frontend will not be served. API only.
)

echo Starting SAWSUBE on http://localhost:8000
python -m backend.main
goto :eof

:error
echo FAILED.
pause
exit /b 1
