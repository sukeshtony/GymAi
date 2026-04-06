@echo off
cd /d "%~dp0"

if not exist .env (
    echo No .env found. Copying from .env.example...
    copy .env.example .env
    echo.
    echo  Please edit backend\.env and set your ANTHROPIC_API_KEY, then re-run.
    pause
    exit /b 1
)

if not exist venv (
    echo Creating virtualenv...
    python -m venv venv
)

call venv\Scripts\activate.bat
pip install -q -r requirements.txt

echo.
echo  FitnessAI Multi-Agent Fitness Backend
echo  http://localhost:8000
echo  API Docs: http://localhost:8000/docs
echo  Frontend: open frontend\index.html in your browser
echo.

python main.py
pause
