@echo off
rem То же, что "Нарезать лист", но с белой обводкой 8 px, как у наклеек.
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
if "%~1"=="" (echo Перетащите картинку-лист на этот файл. & pause & exit /b)
py -3.14 "%~dp0..\cli.py" cut %* --outline 8
echo.
pause
