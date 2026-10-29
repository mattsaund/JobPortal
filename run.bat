@echo off
rem Start JobPortal on Windows (double-click this file, or run it from a terminal).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
if errorlevel 1 pause
