@echo off
chcp 65001 >nul
cd /d %~dp0
py -3 server_gui.py || python server_gui.py
if errorlevel 1 (
  echo.
  echo 启动失败：请确认已安装 Python 3.9+ （勾选 tkinter / Add to PATH）。
  pause
)
