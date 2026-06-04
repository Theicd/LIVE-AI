@echo off
title AI Live Broadcast - Ollama Streamer
color 0A
echo.
echo  ========================================
echo   AI Live Broadcast - Ollama Streamer
echo  ========================================
echo.

REM === הפעל Ollama עם CORS מופעל ===
echo [1/3] מפעיל Ollama עם CORS...
set OLLAMA_ORIGINS=*
start /B cmd /c "ollama serve > nul 2>&1"
timeout /t 3 /nobreak > nul

REM === בדוק שהמודל קיים ===
echo [2/3] בודק מודל glm-4.7-flash-gpu...
ollama list | find "glm-4.7-flash-gpu" > nul
if errorlevel 1 (
    echo [!] מודל לא נמצא. מנסה glm-4.7-flash:q4_k_M...
    ollama list | find "glm-4.7-flash" > nul
    if errorlevel 1 (
        echo [!] שגיאה: המודל לא קיים. הרץ: ollama pull glm-4.7-flash:q4_k_M
        pause
        exit /b 1
    )
)

REM === הפעל שרת HTTP מתוך הספרייה הנכונה ===
echo [3/3] מפעיל שרת HTTP על פורט 8000...
pushd "%~dp0"
start /B python broadcast_server.py
timeout /t 2 /nobreak > nul

REM === פתח דפדפן ===
echo.
echo  ========================================
echo   פותח דפדפן...
echo   http://localhost:8000/broadcast.html
echo  ========================================
echo.
echo  לחץ CTRL+C לעצירה
echo.
start "" "http://localhost:8000/broadcast.html"

REM === שמור ב-loop ===
:loop
timeout /t 60 /nobreak > nul
goto loop
