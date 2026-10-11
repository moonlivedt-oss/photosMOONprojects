@echo off
chcp 65001 >nul
rem Окно библиотеки: входящие, нарезка с предпросмотром, раскладка по разделам.
set PYTHONDONTWRITEBYTECODE=1
py -3.14 -c "import PyQt6, PIL, numpy" 2>nul || (echo Нужны пакеты: запустите Установить.cmd или py -3.14 -m pip install -r _tools\requirements.txt & pause & exit /b)
start "" pyw -3.14 "%~dp0_tools\app.py"
