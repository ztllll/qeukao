# Windows 版接口与模块契约 v1（2026-10-25）

> 服务端、Web 页面与 Windows 客户端之间的接口约定。改接口时同步更新本文。

## 0. 总则
- 测试一律：独立端口 18000–18999、环境变量 `QEUKAO_DATA_DIR` 指向 `mktemp -d` 临时目录；不得使用仓库内 data/。
- **密码**：默认 `112233`，所有密码校验只走 `qk_config.check_admin_password()`。还在用默认密码时（无 passwordHash、也没设 `QEUKAO_ADMIN_PASSWORD`），后台除 `GET /api/admin/me` 和 `POST /api/admin/password` 外一律 403 `MUST_CHANGE_PASSWORD`；`set_admin_password` 拒绝把 112233 设为新密码。新代码里不得出现明文密码字面量（测试除外）。
- 响应信封沿用原项目：成功 `{"success":true,"data":...}`，失败 `{"success":false,"error":{"code","message"}}`。
- 时间一律服务端时钟：`app.now_iso()`（UTC+8，秒级 ISO）。客户端不得用本机时间做任何决策。
- 教室识别沿用原逻辑「按访问 IP 推断」，规则可配置（§3），**不引入 token 识别教室**。
- 原有业务（填报、验收、统计、导入、日志）行为不变，除 §4 明确列出的两处：①验收后进入"无可填报场次"；②转发头只在连接来自本机回环时才信任。
- 文件名不要含 secret/token/credential（.gitignore 会吞掉）。

## 1. 文件所有权（写范围互不重叠）
| 包 | 拥有的文件 | 只读依赖 |
| --- | --- | --- |
| A1 配置与库工具 | qk_config.py、qk_dbtools.py、tests/test_config.py、tests/test_dbtools.py | — |
| A2 服务端核心 | app.py、qk_agents.py、tests/test_agents_http.py | A1 的 API |
| B 服务端 GUI | server_gui.py、run_server.pyw、start_server.bat、open_firewall.bat、build_server_exe.bat | A1/A2 的 API |
| C Go 客户端 | client/**、scripts/build_client.sh、scripts/e2e_client_wine.sh | §5/§6/§7 |
| D 前端 UI | static/** | §5 的 HTTP API |

## 2. 配置文件 `<DATA_DIR>/config.json`
`DATA_DIR` = 环境变量 `QEUKAO_DATA_DIR`，缺省 `<项目目录>/data`。数据库 = `QEUKAO_DB` 或 `<DATA_DIR>/qeukao.sqlite3`。
~~~json
{"version":1,
 "serverName":"考务服务端",
 "host":"0.0.0.0","port":8000,
 "passwordHash":"pbkdf2$200000$<saltHex>$<hashHex>",
 "sessionSecret":"<首次启动随机生成>",
 "enrollKey":"<首次启动随机生成 24 位 urlsafe>",
 "roomRule":{"octet":3,"prefix":"10.10."},
 "backup":{"enabled":true,"dir":"","everyDays":3,"retentionDays":90}}
~~~
- 密码和密钥放配置文件，**不放数据库**（避免导入旧库把密码回滚）。
- `passwordHash` 缺失时：用环境变量 `QEUKAO_ADMIN_PASSWORD`，再缺省 `112233` 做比较。一旦通过 `set_admin_password` 设置，以哈希为准。
- `sessionSecret`：环境变量 `QEUKAO_SESSION_SECRET` 优先，其次配置，缺失则生成并落盘。
- 写文件必须原子（写临时文件再 `os.replace`）；读写加进程内锁。
- `backup.dir` 为空表示 `<项目目录>/backups`。

## 3. Python 模块 API
### qk_config.py（A1）
~~~python
DATA_DIR: Path; CONFIG_PATH: Path; DB_PATH: Path; BASE_DIR: Path
def load() -> dict                      # 深拷贝快照；首次调用创建默认 config.json
def save(patch: dict) -> dict           # 深合并 + 原子写，返回新配置；只允许已知键
def check_admin_password(pw: str) -> bool        # 常量时间比较
def set_admin_password(new_pw: str) -> None      # 4..64 字符且不是默认 112233，否则 ValueError
def session_secret() -> str
def enroll_key() -> str
def regenerate_enroll_key() -> str
def room_from_ip(ip: str) -> dict | None         # {"roomName":"七教室","roomNumber":7}；按 roomRule；1..N（N=后台基本信息的教室数量，默认 30）之外/前缀不符/非 IPv4 → None
def validate_room_rule(rule: dict) -> dict       # octet∈1..4；prefix 为空或形如 "10.10." / "192.168.5."；非法抛 ValueError；返回规范化 rule
def suggest_room_rule(ips: list[str]) -> dict | None
    # 自适应推荐：对 octet=1..4 各自统计"值落在 1..N（教室数量）的 IP 占比"与"不同值个数"，
    # 选占比≥90% 且不同值个数最多者（并列优先 octet=3）；prefix = 该位之前各段全部相同时的公共前缀（如 "10.10."），否则 ""。
    # 返回 {"octet":3,"prefix":"10.10.","matched":n,"total":m}；ips 为空或无合格位 → None
def lan_ipv4_addresses() -> list[str]            # 本机非回环 IPv4，去重；首选私有网段；失败返回 []
def access_urls(port: int) -> list[dict]         # [{"ip","fillUrl","adminUrl"}]
~~~
教室名单来自 qk_config.room_names()（config.json 的 site 段：orgName/orgAddress/roomCount/roomNames；默认「一教室…三十教室」，可在后台基本信息改数量与名称，空名单=按数量自动生成）；CLASSROOM_NAMES 常量已删除。

### qk_dbtools.py（A1）
~~~python
class DbToolError(Exception): ...        # message 为面向用户的中文
def backup_database(dest_dir=None, tag="") -> Path       # sqlite backup API；文件名 qeukao-db-YYYYmmdd-HHMMSS[-tag].sqlite3
def export_database(dest_file) -> Path                    # backup API 写到指定文件
def import_database(src_file) -> dict
    # 1 校验是 SQLite 且 PRAGMA integrity_check=ok 且含 absence_reports 表；失败抛 DbToolError，现库不变
    # 2 先 backup_database(tag="before-import")
    # 3 用 backup API 把 src 写入现库（不替换文件，兼容 WAL）
    # 4 调用 post_import_hook()（由 app 注册，用来 init_db + 补会话状态）
    # 返回 {"backupPath":str,"reportCount":int}
def set_post_import_hook(fn) -> None
# 约束（v1.1）：①模块内部持锁的函数互相调用不得自锁（用 RLock 或拆无锁内部函数）；
# ②backup_database / export_database / import_database 成功后由 qk_dbtools 自己向 operation_logs 追加 db_backup / db_exported / db_imported
#   （GUI 直接调用这些函数，不经过 app 路由）；写日志失败只记 logging，不得让备份/导入失败；
#   写入方式：独立短连接直接 INSERT（表结构见 app.init_db；表不存在则跳过），不得 import app（避免循环依赖）；
#   自动备份(tag="auto")也记 db_backup，severity=info。
def cleanup_old_backups(dest_dir=None, retention_days=None) -> int   # 只删 qeukao-db-*.sqlite3，返回删除数
def list_backups(dest_dir=None) -> list[dict]             # [{"path","name","size","mtime"}] 新→旧
def start_backup_scheduler() -> threading.Thread          # daemon，每 10 分钟检查：enabled 且最新备份距今≥everyDays → 备份并清理
~~~

### app.py（A2）新增/改动的公开入口（GUI 依赖）
~~~python
def init_all() -> None                                    # init_db + 迁移 + 日志清理 + 启动 3 个幂等 daemon 后台线程（日志清理 / 自动备份 / 定时下发调度）；幂等
def build_server(host: str, port: int) -> ThreadingHTTPServer   # 不 serve；调用方自己 serve_forever / shutdown
def main() -> None                                        # init_all + build_server + serve_forever（命令行用）
~~~
app.py 其余：`ADMIN_PASSWORD` 常量删除，8 处校验改走 `qk_config.check_admin_password`（含原先写死 `"112233"` 的 delete_report_group）；`SESSION_SECRET` 改 `qk_config.session_secret()`；`classroom_from_client_ip` 改走 `qk_config.room_from_ip`；`shutil.copy2` 备份改 `qk_dbtools.backup_database(tag="before-excel-import")`；Excel 导入目录改成候选探测（`QEUKAO_EXCEL_IMPORT_DIR` → `%USERPROFILE%\Desktop` → `%USERPROFILE%\OneDrive\Desktop` → `~/桌面` → `~/Desktop`，取第一个存在的）。

### qk_agents.py（A2）供 GUI 使用
~~~python
def build_client_exe(servers: list[str], out_path, name: str = "") -> Path
    # 读模板 <项目目录>/client/dist/qeukao-client-template.exe（环境变量 QEUKAO_CLIENT_TEMPLATE 可覆盖），
    # 追加 §6 的 trailer，写到 out_path；模板不存在抛 FileNotFoundError(中文说明)
def recent_client_ips(limit=200) -> list[str]
def client_summary() -> dict                              # {"total":n,"online":m}
~~~

## 4. 场次状态机（原逻辑的唯一边界改动）
- app_settings 新键 `session_state` ∈ {open, closed}。
- 缺省迁移（init_all 内，import 后也要再跑）：键不存在时，有未验收 drafts → `open`（保持升级后行为不变）；否则 `closed`。
- **open 的唯一入口**：dispatch 触发（立即发送=创建即触发；定时=到点由调度线程触发）。触发时若当前无 drafts → 把该下发的 title（必填）和 examDate（缺省当天）写入 `current_project_title` / `current_exam_date`；有未验收 drafts 时沿用当前场次的这两项（立即下发的回包用 titleKept 告知）。老师提交的草稿标题/日期一律取这两项，老师传来的不算数。
- **closed 的唯一入口**：`accept_reports` 成功（与清空 drafts 同一事务）。
- 非 open 时：`POST /api/current-reports`、`POST /api/current-reports/check-room` 返回 409 `NO_OPEN_SESSION`，消息「当前暂无可填报场次，请联系考务管理员」。其余接口不受限（管理端改/删历史记录照常）。
- 已有定时下发在验收时保持 pending，到点照常触发（用于下一场）。
- 转发头：`resolve_client_ip` 仅当 TCP 对端是 127.0.0.1/::1 时才读 X-Forwarded-For/X-Real-IP/Forwarded，否则用对端地址。

## 5. HTTP API
### 5.1 公开
- `GET /api/admin/analytics?title=&from=&to=&room=`（需登录）→ `{totals, exams[], rooms[], topAbsent[], distribution[], roomHistory[]}`；title 模糊包含、from/to 含两端；与 `/api/admin/reports`、`/summary`、`/export` 共用 app.range_filter（同一口径）。一场 = (标题, 考试日期)。
- `GET /api/session` → `{"open":bool,"title":str,"examDate":str,"closedMessage":"当前暂无可填报场次，请联系考务管理员","serverTime":iso}`
- 其余原有公开接口不变（`/api/client-context` 的教室匹配改用可配置规则）。

### 5.2 Agent（客户端）——头 `X-Qk-Key: <enrollKey>`，缺/错 → 401 `UNAUTHORIZED`；被拉黑 → 403 `CLIENT_BLOCKED`
所有 agent 请求的"教室"一律由 **TCP 对端 IP** + roomRule 现算，不信客户端自报。
- `POST /api/agent/hello` body `{"clientId":str(8..64),"hostname":str,"version":str,"localIps":[str]}` → `{"serverTime","serverName","pollSeconds":25,"room":{"matched":bool,"roomName","roomNumber"}}`。upsert 客户端并记 last_seen；首次出现记日志 client_enrolled。
- `GET /api/agent/poll?clientId=..&wait=25` 长轮询。更新 last_seen；每 0.5s 检查一次，有 notice 立即返回，否则最多 wait 秒（上限 30）后返回空。→ `{"serverTime","session":{"open":bool},"notice":null|{"dispatchId":int,"title":str,"message":str,"openPath":"/"}}`
  - notice 条件（全部满足）：session open ∧ 存在已触发(status=fired)的最新 dispatch D ∧ 该客户端对 D 没有 confirmed/opened 的 ack ∧ （该客户端的教室未匹配，或该教室当前没有 draft）。
- `POST /api/agent/ack` body `{"clientId","dispatchId","state":"shown|confirmed|opened|failed","detail":str?}` → `{"ok":true}`。同一 (dispatch,client) upsert 最新状态。

### 5.3 管理（需 admin cookie，沿用 `require_admin`）
- `POST /api/admin/dispatch` body `{"message"?:str≤200 字 且「显示行数」≤9(缺省"请点击确定填写缺考信息"；空白按缺省处理；\r、\x0b、\x0c、\x1c-\x1e、\x85、\u2028、\u2029 一律规范成 \n)。显示行数 = 各硬行(以 \n 分隔)的 max(1, ⌈加权字数/30⌉) 之和，加权字数中：ASCII、拉丁字母(<U+0250)、常用标点(U+2000–206F)、CJK 与全角字符(见 cjkRanges)每个按 1 计，**其它一律按 2 计**（emoji、符号、箭头、数学字母、希腊/西里尔等约 2em 宽，未知宁可保守；三处实现 qk_agents._weight / admin.js messageWeight / client runeWeight 与同一张 CJK 范围表必须一致）。含孤立代理项等无法编码为 UTF-8 的字符返回 400——一个换行至少占一整行，所以只限字数或只限换行都不能保证弹窗放得下。服务端超限返回 400「弹窗内容太长或换行太多」（提示里写明表情、符号、箭头、生僻字等每个按 2 字计）。**已知取舍**：①②、℃、№、▲ 等实测约 1em 的符号也按 2 计，所以「每行接近 30 字且含这类符号」的文案会被保守地拒绝；放宽需要用真实微软雅黑度量确认后再加进窄表（审查者 S1）,"title":str 1..120（必填，空白 400）,"examDate"?:"YYYY-MM-DD"（缺省当天）,"mode":"now|scheduled","scheduledAt"?:"YYYY-MM-DDTHH:MM[:SS]"（服务器本地时间，无时区）}`。scheduled 必须晚于服务端当前时间，否则 400。→ dispatch 对象（见 live.dispatches[]）；mode=now 时另带 sessionTitle/sessionExamDate（本次事务内场次实际用的表头与日期）和 titleKept（本次填的标题/日期因当前已有未验收数据而未采用时为 true；scheduled 不返回）。
- `POST /api/admin/dispatches/{id}/cancel` 仅 pending 可取消。
- `GET /api/admin/dispatches` → `{"items":[dispatch...]}` 最近 50 条。
- `GET /api/admin/live`：
~~~json
{"serverTime":"iso",
 "session":{"open":true,"title":"","dispatchId":12},
 "summary":{"clientsTotal":30,"clientsOnline":28,"roomsSubmitted":12,"roomsTotal":30},
 "rooms":[{"roomNumber":1,"roomName":"一教室","submitted":true,
           "report":{"expectedCount":45,"actualCount":43,"absentCount":2,"attendanceRate":0.9556,"updatedAt":"iso"},
           "clientIds":["..."]}],
 "clients":[{"clientId":"..","name":"主机名","ip":"10.10.7.23","roomNumber":7,"roomName":"七教室",
             "online":true,"lastSeenAt":"iso","blocked":false,"version":"1.0.0",
             "notice":{"dispatchId":12,"state":"none|shown|confirmed|opened|failed","at":"iso|null"}}],
 "dispatches":[{"id":12,"title":"","message":"..","mode":"now|scheduled","scheduledAt":null,"status":"pending|fired|cancelled|missed",
                "createdAt":"iso","firedAt":"iso|null",
                "counts":{"online":28,"shown":20,"confirmed":18,"opened":18,"failed":0}}]}
~~~
  rooms 项数 = 当前教室名单长度（默认 30；summary.roomsTotal 同；无 report 时 submitted=false,report=null）；online = last_seen 距今 ≤ 40 秒；dispatches 最近 20 条新→旧。
- `POST /api/admin/clients/{clientId}/block` body `{"blocked":bool}`；`DELETE /api/admin/clients/{clientId}`。
- `GET /api/admin/settings` → `{"serverName","roomRule":{"octet","prefix"},"accessUrls":[{"ip","fillUrl","adminUrl"}]}`
- `POST /api/admin/settings/room-rule` body `{"octet","prefix"}` 保存；`POST /api/admin/settings/room-rule/preview` body `{"octet","prefix","ip"}` → `{"matched":bool,"roomName":""}`（不保存）；`GET /api/admin/settings/room-rule/suggest` → `{"suggestion":null|{octet,prefix,matched,total}}`（基于已登记客户端的 IP）。
- `POST /api/admin/password` body `{"oldPassword","newPassword"}`；旧密码错 → 401；新密码非法 → 400。
- `GET /api/admin/client/download` → 绑定了本服务端的客户端 exe（附件名 qeukao-client.exe）；servers = 全部局域网 IPv4:port + 本次请求 Host。模板缺失 → 404 `CLIENT_TEMPLATE_MISSING`。

### 5.4 新增 operation_logs 事件类型（前端要给中文标签）
client_enrolled、dispatch_created、dispatch_cancelled、dispatch_fired、dispatch_missed、session_opened、session_closed、client_blocked、client_unblocked、client_deleted、password_changed、room_rule_changed、db_backup、db_exported、db_imported。

### 5.5 调度
调度线程每 1 秒：pending 且 scheduledAt ≤ now → fired（顺便置 open）；若逾期 > 10 分钟（例如服务停过）→ missed 不触发。

## 6. 绑定客户端文件格式
`<模板 exe 字节><JSON(utf-8)><uint32 小端=JSON长度><魔数 "QKCFG-V1\n" 共 9 字节>`
JSON：`{"v":1,"servers":["http://10.10.0.5:8000","http://192.168.1.8:8000"],"enrollKey":"..","name":"考务服务端"}`。客户端读自己的 exe 尾部取配置；魔数不符 → 无配置（开发模式，读命令行 `--server --key`）。

## 7. 客户端行为规格（Go，仅标准库 syscall，零第三方依赖）
- 目标 `GOOS=windows GOARCH=amd64`，`-H windowsgui`，无控制台、无任何可见窗口（除 `弹窗`）。
- **两进程**：同一 exe。默认=监护进程；`--worker`=工作进程。监护进程启动 worker 并等待：退出码 0（用户在托盘选了退出）→ 监护也退出；其它（崩溃/被结束）→ 2s 后重启。「快速崩溃」= worker 存活不足 1 分钟就退出：连续快速崩溃依次等 2/4/8/16/30s，**第 6 次起每次等 60s**；worker 稳定运行满 1 分钟后计数清零。worker 发现已有另一个 worker 在运行（孤儿）→ 退出码 3，监护 30s 后再试，**不当作用户退出**。监护循环内任何 panic 只当作一次 worker 异常退出，继续重启（监护进程自身不死）。
- **单实例**：命名互斥体，已存在则静默退出。
- **安装与自启**：监护进程首次运行若自身不在 `%LOCALAPPDATA%\QeukaoClient\qeukao-client.exe`：复制自身（含 trailer）到该路径（目标被占用时：把旧文件改名为 `.old` 后再复制，复制失败则回滚；新配置在旧客户端重启后生效）、写 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\QeukaoClient` 指向安装路径、用 `--installed` 参数启动安装路径的副本并退出（带该参数的进程不再安装，避免路径写法不一致时无限自我拉起）。是否「已在安装路径」按文件标识（os.SameFile）判断。已在安装路径时只确保 Run 键存在。**安装失败（目录不可写、Run 键写不进去）不能让客户端不运行：记日志后就地运行。**
- **托盘**：隐藏消息窗口 + Shell_NotifyIconW；图标可用 LoadIcon(IDI_APPLICATION)；悬停提示「缺考上报客户端 - 已连接/连接中」；右键菜单仅「退出」（以及灰色的状态行）；退出 → worker 退出码 0。TaskbarCreated 消息到来时重建图标（资源管理器崩溃恢复）。
- **联网**：servers 列表依次尝试 hello，成功者固定使用，失败则轮换；失败退避 1→2→4…30s。clientId = 首次生成的随机 16 字节 hex，存 `%LOCALAPPDATA%\QeukaoClient\client-id`。401 = 密钥失效，只记日志并 30s 重试。
- **长轮询**：循环 `GET /api/agent/poll?wait=25`（HTTP 超时 35s）。收到 notice 且当前无弹窗 → 弹窗并 ack shown。
- **弹窗**：自绘 Win32 窗口（不是 MessageBox）。WS_POPUP + WS_EX_TOPMOST|WS_EX_TOOLWINDOW；尺寸=主屏 60% 宽（最小 720×420、最大 1100×620）；**居中**；顶部色带 + 标题「考务通知」；正文用大字号（默认 40px，微软雅黑 UI）自动换行居中；**文案较长时自适应**：先缩小字号（**物理像素**最低 16px——按逻辑像素定下限会让高 DPI 屏上更放不下），仍放不下再把窗口加高到 620（不超过主屏高度的 85%），**是否放得下用真实 DrawText(DT_CALCRECT) 度量，不用估算**（估算在英文按词折行、CR/VT 换行、字体行高上都和实际排版不一致），日志里有 `popup: layout WxH font=Npx measured-fits=true|false`；按显示行数规则（见 §5.3）放行的文案，在 100%–146% 缩放下完整可见。DrawText 只在空格处折行、不拆长词，所以客户端显示前对「没有空格且长于 36 的 ASCII 连续串」（URL、长数字、200 个 W）每 12 个字符插一个空格作为折行点；含非 ASCII 的无空格连续串（带音标的拉丁字母、希腊/西里尔、emoji，单个字符可宽到 2em）阈值更严：超过 12 个就每 6 个插一个（`popupText`；**度量仍判定放不下时降级为逐字折行再度量一次**（`layoutPopup`），所以「完整可见」不依赖对每种字符宽度的预判；汉字/假名/谚文/全角字符 DrawText 本身能逐字折行，不处理；ZWJ emoji、组合音标等组合序列不会被从中间拆开；正常文字原样不动，插入的空格只影响显示）。极端情况下若真实度量仍判定放不下，照常弹出并记 `WARNING text does not fully fit`，不会为了排版卡住考务流程（默认文案 12 字始终是 40 逻辑像素）；底部一个大按钮「确定」（≥220×72），回车=确定；**无关闭按钮，WM_CLOSE/Alt+F4 忽略**；SetProcessDPIAware；创建后 SetForegroundWindow（用 AttachThreadInput 技巧抢前台）。每个窗口放在独立的 LockOSThread 线程里跑自己的消息循环。
- **点击确定** → ack confirmed → 打开 Chrome 访问 `<当前 server><openPath>` → 成功 ack opened，失败 ack failed(detail)。Chrome 查找顺序：环境变量 `QEUKAO_CHROME_PATH`（测试用）→ 注册表 App Paths(HKLM、HKCU)→ `%ProgramFiles%`、`%ProgramFiles(x86)%`、`%LocalAppData%` 下 Google\Chrome\Application\chrome.exe。命令 `chrome.exe --new-window <url>`。找不到 Chrome → 用 ShellExecute 默认浏览器打开，ack failed(detail="chrome-not-found,used-default-browser")。
- 弹窗显示期间新的 notice（dispatchId 更大）→ 仅更新"当前 dispatchId"，不叠加窗口；点击确定时 ack 当前最大 id。
- 日志：`%LocalAppData%\QeukaoClient\client.log`，>1MB 轮转一次；不弹任何错误框。
- 构建/测试：`scripts/build_client.sh` 产出 `client/dist/qeukao-client-template.exe`；协议、trailer 解析、退避逻辑用 `go test`（非 Windows 文件用 build tag 提供桩，保证 Linux 下 go vet/test 通过）；`scripts/e2e_client_wine.sh` 在 Xvfb+wine 里真启动客户端 ↔ 真服务端，截图弹窗并点击确定，校验服务端 ack。

## 8. 验收命令（每个包交付前必须全绿，并把输出贴给 lead）
- A1：`python3 -m unittest tests.test_config tests.test_dbtools -v`
- A2：`python3 -m py_compile app.py qk_agents.py && python3 -m unittest tests.test_agents_http -v`
- B：`xvfb-run -a python3 server_gui.py --selftest`（实现 `--selftest`：起 GUI、起服务、断言 /api/health、关闭，退出码 0）
- C：`cd client && go vet ./... && go test ./... && cd .. && scripts/build_client.sh && scripts/e2e_client_wine.sh`
- D：Playwright/agent-browser 截图每个页面（桌面 1440、平板 820、手机 390），贴路径。
