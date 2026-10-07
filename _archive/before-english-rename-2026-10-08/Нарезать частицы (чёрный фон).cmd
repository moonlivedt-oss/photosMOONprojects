@echo off
rem Для листов частиц на чёрном фоне: режет, чёрный фон оставляет (в приложении режим Screen).
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
if "%~1"=="" (echo Перетащите лист на этот файл. & pause & exit /b)
py -3.14 "%~dp0картинки.py" нарезать %* --fon ostavit
echo.
pause
