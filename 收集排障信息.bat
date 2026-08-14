@echo off
chcp 65001 >nul
set "BASE=%~dp0"
echo 正在收集排障信息，请稍候...
"%BASE%python\python.exe" "%BASE%collect_diag.py"
pause
