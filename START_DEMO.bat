@echo off
setlocal
cd /d "%~dp0"
echo DCF-BAS - Final-year booking demonstration
echo Preparing Python dependencies. Please keep this window open.
if exist ".venv\Scripts\python.exe" goto install
where py >nul 2>&1
if errorlevel 1 goto python_fallback
py -m venv .venv
if errorlevel 1 goto failed
goto install
:python_fallback
python -m venv .venv
if errorlevel 1 goto failed
:install
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Opening http://localhost:8000 when the server is ready.
echo Use Teacher demonstration in the website to select sample roles.
".venv\Scripts\python.exe" server.py demo --open-browser
if errorlevel 1 goto failed
goto end
:failed
echo.
echo The demo could not start. Read the error above.
echo If port 8000 is busy, stop your previous server with Ctrl+C first.
echo Python 3.12 or later is required.
:end
pause
