@echo off
REM Run this file from inside the Philsys_Output folder (double-click it or run from cmd).
setlocal

cd /d "%~dp0"

REM 1. Create the virtual environment if it doesn't exist yet
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

REM 2. Activate it
call venv\Scripts\activate.bat

REM 3. Install/update dependencies
echo Installing dependencies...
pip install -r requirements.txt

REM 4. Set local login credentials (change these if you want)
set APP_USERNAME=admin
set APP_PASSWORD=changeme

REM 5. Run the app
echo.
echo Starting server at http://127.0.0.1:5000
echo Login with APP_USERNAME / APP_PASSWORD shown above.
echo Press CTRL+C to stop.
echo.
python wsgi.py

pause
