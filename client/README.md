# 缺考上报 Windows 客户端

纯 Go 标准库 + syscall，无 CGO、无第三方模块。Go 1.22+；目标 Windows amd64。

**最低系统：Windows 10 / Windows Server 2016 及以上。** Go 1.21 起官方不再支持 Windows 7/8/8.1，用本仓库工具链（Go 1.22+）构建的 exe 在 Win7/8 上无法启动。教室机若有 Win7/8，需用 Go 1.20 或更早的工具链另行构建（未验证，也不是推荐方案）；请在分发前确认教室机系统版本。
接口唯一依据：[Windows 契约](../docs/windows-contract.md) §5.2、§6、§7。

## 构建与验收

从独立项目根目录运行：

```sh
cd client && go vet ./... && go test ./... && cd ..
scripts/build_client.sh
scripts/e2e_client_wine.sh
```

构建脚本离线编译，固定使用 `CGO_ENABLED=0 GOOS=windows GOARCH=amd64`
与 `-ldflags "-s -w -H windowsgui"`，模板输出到 `client/dist/qeukao-client-template.exe`。
服务端按契约追加 JSON trailer 后即可分发；模板不包含真实 enrollment key。
`dist/` 与 e2e 生成的 exe 均不进 Git。

## Windows 调试

未绑定 trailer 时可用：

```powershell
$env:QEUKAO_CLIENT_NO_INSTALL="1"
$env:QEUKAO_CLIENT_HOME="$env:TEMP\qk-client-debug"
.\qeukao-client-template.exe --server http://127.0.0.1:18000 --key <测试enrollKey> --no-guard
```

默认进程安装到 `%LOCALAPPDATA%\QeukaoClient\qeukao-client.exe`、配置 HKCU Run，
然后由监护进程启动同一 exe 的 `--worker`。`--no-guard` 仅跑 worker，不安装。
监护和 worker 各有命名 mutex，重复启动静默退出。托盘右键「退出」终止 worker，
退出码 0 让监护一起退出；异常退出由监护退避重启。

测试覆盖：
- `QEUKAO_CLIENT_NO_INSTALL=1`：跳过复制自身与 Run 键；默认仍正常安装。
- `QEUKAO_CLIENT_HOME`：覆盖 client-id 与日志目录，不改变默认安装位置。
- `QEUKAO_CHROME_PATH`：优先指定 Chrome 可执行文件。

日志为数据目录的 `client.log`，超过 1MB 保留一次轮转 `client.log.1`。
业务时机和场次状态仅使用服务端 notice；本机时钟仅用于日志、联网退避与崩溃速率保护。
通知确认串行重试 shown → confirmed → opened/failed，避免瞬时断网造成 ACK 倒序。
弹窗期间收到更大 dispatchId 仅替换确认目标，不重画正文、不堆叠窗口。

## Wine e2e

需要 wine、Xvfb/xvfb-run、xauth、xdotool、Python 3.9+、Go，截图用 ImageMagick import
（或 xwd + convert）。脚本只能通过 `xvfb-run -a` 创建隔离显示；不会用 DISPLAY=:0。
固定专属 `WINEPREFIX=$HOME/.cache/qk-client-wine`，若已存在则拒绝运行，避免碰其他会话。
首次执行 `wine wineboot -i`；标准库假服务端自动选择 18000–18999 的空闲端口。

`e2e/stub_server.py` 提供 hello/poll/ack 和 `/_test/fire`、`/_test/acks`。
`e2e/fakechrome/main.go` 编译成临时 fakechrome.exe，仅记录实际收到的 URL。
测试运行默认监护 + worker、读取真实绑定 trailer，查找「考务通知」、发送 Alt+F4 验证不关闭、
截图到 `/tmp/qk-e2e/`、发送 Return，断言 shown → confirmed → opened 及 Chrome URL。
Wine 不保证有可见托盘，因此只断言启动日志 `tray: icon added ok/err=...`。
结束只清理本次 PID、临时目录与带所有权标记的专属 Wine 前缀；截图保留作验收证据。

真实 Windows 的 Explorer 重启托盘恢复、Run 自启与高 DPI 前台策略仍应现场验收；
Wine e2e 证明 Win32 消息循环、弹窗绘制、键盘确认、真实跨进程 Chrome 启动与协议互通。
