@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
title 科研工作台
python workbench\scripts\start.py
if errorlevel 1 (
  echo.
  echo 启动失败，请根据上方提示处理后重试。
  pause
)
