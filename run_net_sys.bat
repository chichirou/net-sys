@echo off
chcp 65001 >nul
cd /d "%~dp0"
title NET::SYS MONITOR

REM ===== 必要なライブラリの確認 =====
REM psutil / pywin32 / wmi / Pillow が揃っているか確認し、
REM 足りなければインストールする (初回のみ実行される)
python -c "import psutil, win32api, wmi, PIL" 2>nul
if errorlevel 1 (
    echo 必要なライブラリをインストールしています...
    python -m pip install psutil pywin32 wmi Pillow
    echo.
)

REM ===== 起動 =====
python net_sys.py

REM 異常終了したときだけ画面を残してエラーを確認できるようにする
if errorlevel 1 pause
