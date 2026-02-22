@echo off
title FastAPI - dev

echo Activating virtual environment...
call .\.venv\Scripts\activate.bat

echo Starting uvicorn...
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

echo.
echo Server stopped.
pause