@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=%~dp0..\python\python.exe"
if not exist "%PY%" set "PY=python"
echo 3 круга: настройки, блокнот, калькулятор, папка, скрин, экран, OCR, эмоции
echo Поиск в браузере: --browser
echo Живой LLM: --llm
"%PY%" "%~dp0selftest_human.py" %*
echo.
pause
