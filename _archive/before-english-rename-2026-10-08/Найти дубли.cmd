@echo off
rem Ищет одинаковые картинки в этой папке, лишние копии переносит в _дубли (не удаляет).
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
py -3.14 "%~dp0картинки.py" дубли
py -3.14 "%~dp0картинки.py" галерея
echo.
pause
