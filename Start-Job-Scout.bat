@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   AI Job Scout is starting...
echo   This window is the website's server. Keep it
echo   open while using the tool (you can minimize it).
echo   Close this window to stop the tool.
echo ============================================
rem Open the browser after 3 seconds (let the server start first)
start "" cmd /c "timeout /t 3 /nobreak >nul & start "" http://127.0.0.1:5050"
python app.py
echo.
echo The program has exited. If there is a red error above, copy the whole thing and ask an AI assistant (ChatGPT / Claude, etc.).
pause
