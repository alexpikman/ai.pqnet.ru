@echo off
setlocal
cd /d "%~dp0"
set "PQ_PORT=8765"
if not exist data mkdir data
python --version
if errorlevel 1 (
  echo ERROR: Python 3 is required.
  pause
  exit /b 1
)
python -c "import psutil" >nul 2>&1
if errorlevel 1 (
  echo Installing psutil for detailed system telemetry...
  python -m pip install -r requirements.txt
  if errorlevel 1 echo WARNING: psutil installation failed. Basic telemetry will still run.
)
echo.
echo Project folder: %CD%
echo Checking for an old server on port %PQ_PORT%...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PQ_PORT% .*LISTENING"') do (
  echo Stopping process %%P using port %PQ_PORT%...
  taskkill /F /PID %%P >nul 2>&1
)
timeout /t 1 /nobreak >nul
echo Starting server from: %CD%\server.py
echo Open http://127.0.0.1:%PQ_PORT%
python "%CD%\server.py"
echo.
echo Server process ended with code %ERRORLEVEL%.
pause
