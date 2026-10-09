@echo off
chcp 65001 >nul
rem Если окно библиотеки не запускается: проверить базу и настройки и починить из резервной копии.
set PYTHONDONTWRITEBYTECODE=1
py -3.14 "%~dp0cli.py" repair fix
echo.
echo Список копий: py -3.14 "%~dp0cli.py" repair list
echo Вернуть последнюю: py -3.14 "%~dp0cli.py" repair restore latest
pause
