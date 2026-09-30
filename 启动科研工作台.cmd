@echo off & chcp 65001 >nul & set "PYTHONUTF8=1" & python "%~dp0workbench\scripts\start.py" & if errorlevel 1 pause
