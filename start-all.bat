@echo off
REM Windows launcher (PowerShell/CMD/double-click): start both services.
REM   FastAPI AI service  (port 8000) -> logs\uvicorn.log
REM   Spring Boot web app (port 8080) -> logs\spring.log
REM Git Bash users can use the bash version: ./start-all
chcp 65001 >nul
cd /d "%~dp0"
if not exist logs mkdir logs

echo 启动 AI 服务(FastAPI, 端口 8000)...
start "interview-agent-ai" /min cmd /c "python -m uvicorn interview_agent.server:app --port 8000 > logs\uvicorn.log 2>&1"

echo 启动 Web 服务(Spring Boot, 端口 8080)...
start "interview-agent-web" /min cmd /c "mvn -f web spring-boot:run > logs\spring.log 2>&1"

echo.
echo 正在等待服务就绪(最多约 40 秒)...
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
echo [OK] 双服务已就绪!
echo.
echo   Web 页面: http://localhost:8080/practice
echo   AI  服务: http://localhost:8000
echo   日志:     logs\uvicorn.log 与 logs\spring.log
echo.
start http://localhost:8080/practice
exit /b 0

:givup
echo [FAIL] Web 服务约 40 秒内未就绪,请查看 logs\spring.log
echo   AI  服务: http://localhost:8000
echo   手动打开: http://localhost:8080/practice
exit /b 1
