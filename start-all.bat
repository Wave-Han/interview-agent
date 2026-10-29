@echo off
REM Windows launcher (PowerShell/CMD/double-click): start both services.
REM   FastAPI AI service  (port 8000) -> logs\uvicorn.log
REM   Spring Boot web app (port 8080) -> logs\spring.log
REM NOTE: keep this file ASCII-only. cmd parses batch files with the active
REM code page (GBK on zh-CN Windows) BEFORE chcp takes effect, so any
REM non-ASCII text here breaks into garbage commands.
REM Git Bash users: use the bash version ./start-all instead.
cd /d "%~dp0"
if not exist logs mkdir logs

echo Starting AI service (FastAPI, port 8000)...
start "interview-agent-ai" /min cmd /c "python -m uvicorn interview_agent.server:app --port 8000 > logs\uvicorn.log 2>&1"

echo Starting Web service (Spring Boot, port 8080)...
start "interview-agent-web" /min cmd /c "mvn -f web spring-boot:run > logs\spring.log 2>&1"

echo.
echo Waiting for services (up to ~40s)...
set /a tries=0
:waitloop
set /a tries+=1
curl -s -o nul -w "%%{http_code}" http://localhost:8080/practice > "%TEMP%\ia_web_code" 2>nul
set /p webcode=<"%TEMP%\ia_web_code"
if "%webcode%"=="200" goto ready
if %tries% geq 20 goto givup
timeout /t 2 /nobreak >nul
goto waitloop

:ready
echo [OK] Both services ready!
echo.
echo   Web page : http://localhost:8080/practice
echo   AI svc   : http://localhost:8000
echo   Logs     : logs\uvicorn.log , logs\spring.log
echo.
start http://localhost:8080/practice
exit /b 0

:givup
echo [FAIL] Web not ready in ~40s. Check logs\spring.log
echo   AI svc   : http://localhost:8000
echo   Open manually: http://localhost:8080/practice
exit /b 1
