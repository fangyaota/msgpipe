@echo off
set PY=D:\\Python\\Python315\\python.exe
set PYTHONIOENCODING=utf-8
"%PY%" "%~dp0find_image_key.py" > "%~dp0find_image_key.log" 2>&1
