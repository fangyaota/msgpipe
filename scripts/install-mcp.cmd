@echo off
setlocal
set "PYTHONIOENCODING=utf-8"
if not defined MSGPIPE_PY set "MSGPIPE_PY=python"
"%MSGPIPE_PY%" "%~dp0install_mcp.py" %*
