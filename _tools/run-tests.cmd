@echo off
chcp 65001 >nul
rem Все тесты: ядро (нарезка, правка, выгрузка, промпты, база), эталонные листы, операции для ИИ и сервер MCP.
set PYTHONDONTWRITEBYTECODE=1
cd /d "%~dp0"
py -3.14 -m unittest discover -s tests
pause
