@echo off
rem Перетащите картинки или папку: рядом появятся .webp (длинная сторона не больше 1920).
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
if "%~1"=="" (echo Перетащите картинки на этот файл. & pause & exit /b)
py -3.14 "%~dp0картинки.py" конвертировать %* --v webp --max 1920
echo.
pause
