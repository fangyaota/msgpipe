@echo off
setlocal
set "TEMP=D:\Workspace\msgpipe\state\xxt\tmp"
set "TMP=%TEMP%"
set "PLAYWRIGHT_BROWSERS_PATH=D:\Workspace\msgpipe\tools\xxt\browsers"
set "PYTHONIOENCODING=utf-8"
"D:\Workspace\msgpipe\tools\xxt\chaoxing-agent-cli-main\.venv\Scripts\python.exe" "%~dp0smartestu_assignments.py" %*
