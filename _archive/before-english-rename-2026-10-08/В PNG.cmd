@echo off
rem Перетащите картинки или папку: рядом появятся .png.
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
if "%~1"=="" (echo Перетащите картинки на этот файл. & pause & exit /b)
py -3.14 "%~dp0картинки.py" конвертировать %* --v png
echo.
pause
