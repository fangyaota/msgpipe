@echo off
set "XXT_HOME=%~dp0"
set "MSGPIPE_HOME=%~dp0..\.."
set "TEMP=%XXT_HOME%tmp"
set "TMP=%XXT_HOME%tmp"
set "PLAYWRIGHT_BROWSERS_PATH=%XXT_HOME%browsers"
set "XXT_STATE_DIR=%MSGPIPE_HOME%\state\xxt"
set "PYTHONIOENCODING=utf-8"
"%XXT_HOME%chaoxing-agent-cli-main\.venv\Scripts\xxt.exe" %*
