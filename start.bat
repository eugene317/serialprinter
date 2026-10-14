@echo off
rem Serial Printer: sets itself up on the first run, then opens http://localhost:5003
cd /d "%~dp0"
if not exist venv\Scripts\python.exe (
    echo First run - creating the Python environment...
    py -3 -m venv venv 2>nul || python -m venv venv || (
        echo Python 3 is not installed. Get it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
        pause
        exit /b 1
    )
)
venv\Scripts\python.exe -m pip install -q --disable-pip-version-check -r requirements.txt || (
    echo Installing the requirements failed - check the internet connection.
    pause
    exit /b 1
)
start "" cmd /c "timeout /t 2 >nul & start http://localhost:5003"
venv\Scripts\python.exe app.py
