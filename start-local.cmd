@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0subjects-learning-2\scripts\start.ps1"
if errorlevel 1 pause
