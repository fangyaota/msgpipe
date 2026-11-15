@echo off

set "PYTHONIOENCODING=utf-8"

set "PYTHONUTF8=1"

if not defined MSGPIPE_PY set "MSGPIPE_PY=python"
"%MSGPIPE_PY%" "%~dp0msgscan.py" %*

