@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul

where py >nul 2>nul
if errorlevel 1 goto TRY_PYTHON
py -3 -m venv .venv
goto INSTALL

:TRY_PYTHON
where python >nul 2>nul
if errorlevel 1 goto NOPY
python -m venv .venv
goto INSTALL

:NOPY
echo Python was not found. Install Python 3 first.
pause
exit /b 1

:INSTALL
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
echo.
echo Installation complete. Now run run_mobile.bat
pause
endlocal
