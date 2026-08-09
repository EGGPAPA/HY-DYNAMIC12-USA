@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul

set "PY=.venv\Scripts\python.exe"
if exist "%PY%" goto RUN

echo.
echo HY MOBILE: Python virtual environment was not found.
echo Run install.bat first, then run this file again.
echo.
pause
exit /b 1

:RUN
"%PY%" run_mobile.py
if errorlevel 1 (
  echo.
  echo HY MOBILE stopped with an error.
  pause
)
endlocal
