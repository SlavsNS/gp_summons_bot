@echo off
chcp 65001 > nul
title Telegram Bot - GP Summons Monitor

echo ========================================================
echo   Telegram Bot: Моніторинг повісток Офісу Генпрокурора
echo ========================================================
echo.

where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set PYTHON_CMD=py
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        set PYTHON_CMD=python
    ) else (
        echo [ПОМИЛКА] Python не знайдено на системі!
        pause
        exit /b 1
    )
)

echo Встановлення залежностей...
%PYTHON_CMD% -m pip install -r requirements.txt

echo.
echo Запуск бота...
%PYTHON_CMD% bot.py

pause
