@echo off
rem Перетащите логотип: рядом появится .ico с размерами 16-256 px.
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
if "%~1"=="" (echo Перетащите картинку на этот файл. & pause & exit /b)
py -3.14 "%~dp0картинки.py" конвертировать %* --v ico
echo.
pause
