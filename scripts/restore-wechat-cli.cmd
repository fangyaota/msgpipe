@echo off
rem 从 state\wechat 还原 ~\.wechat-cli（不含 deps，deps 需要本机重装，见 README 第 3 节）
setlocal
set "SRC=%~dp0..\state\wechat"
set "DST=%USERPROFILE%\.wechat-cli"
if not exist "%DST%" mkdir "%DST%"
xcopy "%SRC%\*" "%DST%\" /E /I /Q /Y >nul
echo [ok] 已还原配置与密钥到 %DST%
echo    下一步: D:/Python/Python315/python.exe -m pip install --target "%%USERPROFILE%%\.wechat-cli\deps" --upgrade pycryptodome psutil click zstandard -i https://mirrors.aliyun.com/pypi/simple
