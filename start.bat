@echo off
echo ==================================================
echo   A-Share Pro Trader - Setup and Start
echo ==================================================

echo.
echo [1/3] Checking dependencies...
echo Installing required python packages...
pip install fastapi uvicorn akshare pandas ta sqlalchemy yfinance >nul 2>&1

echo.
echo [2/3] Initializing database...
python -c "from backend.data_manager import init_db; init_db()"

echo.
echo [3/3] Starting server...
echo Access the application at http://localhost:8000
echo.
uvicorn backend.main:app --host 0.0.0.0 --port 8000

pause
