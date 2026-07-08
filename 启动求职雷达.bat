@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   AI Job Scout 正在启动...
echo   这个窗口是网站的服务器，用的时候别关，
echo   可以最小化。想关掉工具就关掉这个窗口。
echo ============================================
rem 3 秒后自动打开浏览器（等服务器先起来）
start "" cmd /c "timeout /t 3 /nobreak >nul & start "" http://127.0.0.1:5050"
python app.py
echo.
echo 程序已退出。如果上面有红色报错，整段复制去问 claude.ai 即可。
pause
