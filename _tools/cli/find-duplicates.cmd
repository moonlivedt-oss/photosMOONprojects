@echo off
rem Ищет одинаковые картинки в этой папке, лишние копии переносит в _duplicates (не удаляет).
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
py -3.14 "%~dp0..\cli.py" dupes
py -3.14 "%~dp0..\cli.py" gallery
echo.
pause
