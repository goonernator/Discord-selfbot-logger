@echo off
echo ============================================================
echo Discord Selfbot Logger - Starting All Services
echo ============================================================
echo.

echo Starting web server...
start "Discord Web Server" python start_web_server.py

echo Waiting for web server to initialize...
timeout /t 3 /nobreak >nul

echo Starting Discord client...
start "Discord Client" python main.py

echo.
echo ============================================================
echo Both services started successfully!
echo Web Dashboard: http://127.0.0.1:5002
echo.
echo Two separate windows have been opened:
echo - Discord Web Server
echo - Discord Client
echo.
echo Close those windows to stop the services.
echo ============================================================
echo.
pause