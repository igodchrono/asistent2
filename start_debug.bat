@echo on
chcp 65001 >nul
setlocal
cd /d "%~dp0data"
echo ========================================
echo  Lisichka - DEBUG (live output)
echo ========================================
echo Folder: %CD%

set "PY=%~dp0python\python.exe"
if not exist "%PY%" (
  where python >nul 2>&1 && set "PY=python"
)

echo Using Python: %PY%
echo ========================================

"%PY%" main.py
set ERR=%ERRORLEVEL%

echo.
echo ========================================
echo Exit code: %ERR%
echo ========================================
pause
endlocal