@echo off
:: Проверка наличия Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python не найден! Пожалуйста, установите Python и добавьте его в PATH.
    pause
    exit /b
)

:: Попытка запустить приложение через pythonw (без консоли)
start "" pythonw mouse_info_app.py

:: Если возникла ошибка запуска
if %errorlevel% neq 0 (
    echo Ошибка при запуске приложения. 
    echo Попробуйте запустить через обычный python для отладки:
    python mouse_info_app.py
    pause
)
