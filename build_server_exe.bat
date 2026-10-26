@echo off
chcp 65001 >nul
rem 说明：把服务端 GUI 打包为单个 exe（仅在 Windows 上由用户执行）。
rem 路径约定（tests/test_frozen_paths.py 钉住）：static 从打包内部读取（--add-data）；
rem   data\、backups\ 在 exe 所在目录。客户端模板：构建时若 client\dist\qeukao-client-template.exe 已存在会被打进包里（--add-data）；
rem   也可放在 exe 旁的 client\dist\，或用环境变量 QEUKAO_CLIENT_TEMPLATE 指定，三处任选其一，否则"生成绑定客户端"会提示模板缺失。
cd /d %~dp0
where pyinstaller >nul 2>&1
if errorlevel 1 (
  python -m PyInstaller --version >nul 2>&1
  if errorlevel 1 (
    echo 未检测到 PyInstaller，请先执行：pip install pyinstaller
    pause
    exit /b 1
  )
)
set ADD_CLIENT=
if exist "client\dist\qeukao-client-template.exe" set ADD_CLIENT=--add-data "client\dist;client\dist"
if not defined ADD_CLIENT echo 提示：没找到 client\dist\qeukao-client-template.exe，打出的服务端将不能生成客户端；请先在装有 Go 的机器上运行 scripts\build_client.sh 并拷到这里。
python -m PyInstaller --noconsole --onefile --name QeukaoServer --add-data "static;static" --add-data "docs;docs" %ADD_CLIENT% --hidden-import app --hidden-import qk_config --hidden-import qk_dbtools --hidden-import qk_agents server_gui.py
if errorlevel 1 (
  echo 打包失败。
  pause
  exit /b 1
)
echo 完成：dist\QeukaoServer.exe
pause
