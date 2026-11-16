@echo off
rem 把本项目的 skills\ 同步到 DSH 技能目录（DSH 只从那里发现技能）
setlocal
set "SRC=%~dp0..\skills"
set "DST=%USERPROFILE%\.dsh\skills"
if not exist "%DST%" mkdir "%DST%"
for %%S in (wechat-todo wechat-local wecom-local) do (
  if exist "%DST%\%%S" rmdir /s /q "%DST%\%%S"
  xcopy "%SRC%\%%S" "%DST%\%%S" /E /I /Q /Y >nul
  echo [ok] %%S -^> %DST%\%%S
)
rem 技能目录里的 msgscan.cmd 是转发器，靠 home.txt 找到本项目
set "HOME_TXT=%DST%\wechat-todo\scripts\home.txt"
for %%P in ("%~dp0..") do > "%HOME_TXT%" echo %%~fP
echo [ok] 已写入项目路径 -^> %HOME_TXT%
echo.
echo 技能已同步。重启会话或新开对话后生效。
