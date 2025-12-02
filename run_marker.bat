@echo off
setlocal enabledelayedexpansion

REM === Настройки ===
set VENV_DIR=.venv
set PYTHON=python

echo [*] Checking virtual environment...

REM === Создание venv, если его нет ===
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [*] Creating virtual environment in %VENV_DIR% ...
    %PYTHON% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [!] Failed to create virtual environment.
        pause
        exit /b 1
    )
) else (
    echo [*] Virtual environment already exists.
)

REM === Активация venv ===
echo [*] Activating virtual environment...
call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 (
    echo [!] Failed to activate virtual environment.
    pause
    exit /b 1
)

REM === Установка зависимостей ===
if exist requirements.txt (
    echo [*] Installing/updating dependencies from requirements.txt ...
    pip install --upgrade pip
    pip install -r requirements.txt
) else (
    echo [!] requirements.txt not found, skipping dependency install.
)

REM === Запуск основного скрипта ===
echo [*] Running mark_ddos_match.py %* ...
python mark_ddos_match.py interactive %* 
set EXITCODE=%ERRORLEVEL%

echo [*] Script finished with exit code %EXITCODE%.
pause
exit /b %EXITCODE%
