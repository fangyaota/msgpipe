@echo off
setlocal
for %%i in ("%~dp0..") do set "PROJ=%%~fi"
set "TEMP=%PROJ%\state\xxt\tmp"
set "TMP=%TEMP%"
set "PLAYWRIGHT_BROWSERS_PATH=%PROJ%\tools\xxt\browsers"
set "PYTHONIOENCODING=utf-8"
"%PROJ%\tools\xxt\chaoxing-agent-cli-main\.venv\Scripts\python.exe" "%~dp0smartestu_assignments.py" %*
