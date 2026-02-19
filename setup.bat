@echo off
echo Setting up environment...

:: Create virtual environment if not exists
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

:: Activate venv
call venv\Scripts\activate

:: Upgrade pip
python -m pip install --upgrade pip

:: Install dependencies
echo Installing dependencies...
:: Install core dependencies first to avoid conflicts
pip install "pydantic>=2.0" "pydantic-settings>=2.0"
pip install "sqlalchemy>=2.0" "sqlmodel>=0.0.32"
pip install "memu-py>=1.3.0"
pip install "openai>=1.0.0" "httpx>=0.28.0" "tiktoken>=0.5.0"
pip install "rich>=13.0.0" "python-dotenv>=1.0.0"

:: Create .env if not exists
if not exist .env (
    echo Creating .env file...
    copy .env.example .env
    echo Please edit .env and add your OPENAI_API_KEY
)

echo Setup complete!
echo To run: venv\Scripts\python main.py
pause
