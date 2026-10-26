@echo off
chcp 65001 >nul
rem 用法：open_firewall.bat [端口]   默认 8000；需要管理员权限
set PORT=%1
if "%PORT%"=="" set PORT=8000
net session >nul 2>&1
if errorlevel 1 (
  echo 需要管理员权限：请右键本文件，选择“以管理员身份运行”。
  pause
  exit /b 1
)
netsh advfirewall firewall delete rule name="Qeukao Server" >nul 2>&1
netsh advfirewall firewall add rule name="Qeukao Server" dir=in action=allow protocol=TCP localport=%PORT%
if errorlevel 1 (
  echo 添加防火墙规则失败。
  pause
  exit /b 1
)
echo 已放行入站 TCP 端口 %PORT%。
pause
