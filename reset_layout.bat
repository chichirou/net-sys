@echo off
cd /d "%~dp0"
title RESET LAYOUT

REM Remove only "dashboard_layout" from net_sys_config.json
REM (theme / alerts / power rate / intro text are kept)
python -c "import json,os;p='net_sys_config.json';d=(json.load(open(p,encoding='utf-8')) if os.path.exists(p) else {});had='dashboard_layout' in d;d.pop('dashboard_layout',None);json.dump(d,open(p,'w',encoding='utf-8'),ensure_ascii=False,indent=2);print('OK: removed dashboard_layout' if had else 'dashboard_layout was not present')"

echo.
echo Done. Start the app - BATTERY and POWER will be side-by-side (3-split).
echo You only need to run this once.
echo.
pause
