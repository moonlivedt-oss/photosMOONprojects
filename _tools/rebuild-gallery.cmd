@echo off
rem Пересобрать Gallery.html по картинкам этой папки.
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
py -3.14 "%~dp0cli.py" gallery
echo.
pause
