@echo off
rem 真正的逻辑在项目的 scripts\msgscan.py，这里只是转发。
rem 项目位置按顺序取：MSGPIPE_HOME 环境变量 → 本目录 home.txt → %USERPROFILE%\msgpipe
setlocal
if not defined MSGPIPE_HOME if exist "%~dp0home.txt" set /p MSGPIPE_HOME=<"%~dp0home.txt"
if not defined MSGPIPE_HOME set "MSGPIPE_HOME=%USERPROFILE%\msgpipe"
if not exist "%MSGPIPE_HOME%\scripts\msgscan.cmd" (
  echo [!!] 找不到项目：%MSGPIPE_HOME%
  echo      设一下环境变量 MSGPIPE_HOME，或在本文件同目录放 home.txt 写项目路径。
  exit /b 1
)
call "%MSGPIPE_HOME%\scripts\msgscan.cmd" %*
