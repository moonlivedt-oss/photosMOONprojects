@echo off
chcp 65001 >nul
rem Тесты ядра библиотеки (нарезка, правка, выгрузка, промпты, база) и сверка с эталонными листами.
set PYTHONDONTWRITEBYTECODE=1
cd /d "%~dp0"
py -3.14 "тесты\тест_картинки.py"
pause
