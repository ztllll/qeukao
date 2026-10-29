#!/usr/bin/env bash
# 全链路联调：真实服务端(app.py) + 从服务端「下载绑定客户端」接口取得的 Go exe（wine 运行）。
# 隔离（契约 §0）：xvfb-run 起的受控 Xvfb（绝不碰真实 DISPLAY）、专属 WINEPREFIX、临时数据目录与临时 DB、
# 端口只在 18000-18999 里挑、只清理本脚本自己启动的进程与目录。
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
LOCK=""; TMP=""; SERVER_PID=""; OWN=0
WINEPREFIX_DIR="$HOME/.cache/qk-full-e2e-wine"
cleanup() {
  st=$?; trap - EXIT INT TERM
  if [[ -n "$SERVER_PID" ]]; then kill "$SERVER_PID" 2>/dev/null || true; wait "$SERVER_PID" 2>/dev/null || true; fi
  if [[ "$OWN" == 1 && -f "$WINEPREFIX_DIR/.qk-owned" ]]; then
    WINEPREFIX="$WINEPREFIX_DIR" wineserver -k || true; WINEPREFIX="$WINEPREFIX_DIR" wineserver -w || true
    rm -rf -- "$WINEPREFIX_DIR"; echo "cleaned owned wine prefix"
  fi
  if [[ -n "$TMP" && "$TMP" == /tmp/qk-full-e2e.* && -d "$TMP" ]]; then rm -rf -- "$TMP"; fi
  if [[ -n "$LOCK" ]]; then rmdir "$LOCK" 2>/dev/null || true; fi
  exit "$st"
}
trap cleanup EXIT INT TERM   # 先注册清理，再获取任何资源

# 入口：外层无条件交给 xvfb-run 起受控 Xvfb；内层必须确认自己确实是 xvfb-run 的后代，
# 不能只看 DISPLAY 字符串——DISPLAY=:1 / :0.0 照样会指向真实桌面。
if [[ "${1:-}" != --inside-xvfb ]]; then
  exec xvfb-run -a -s '-screen 0 1440x900x24' bash "$0" --inside-xvfb
fi
pid=$$; under_xvfb_run=0
while [[ "$pid" -gt 1 ]]; do
  if tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q 'xvfb-run'; then under_xvfb_run=1; break; fi
  pid="$(ps -o ppid= -p "$pid" | tr -d ' ')"
done
[[ "$under_xvfb_run" == 1 ]] || { echo "拒绝运行：当前进程不在 xvfb-run 之下，DISPLAY=${DISPLAY:-} 可能是真实桌面" >&2; exit 2; }
[[ -n "${DISPLAY:-}" ]] || exit 2

if ! command -v wineserver >/dev/null && [[ -x /usr/lib/x86_64-linux-gnu/wine/wineserver ]]; then export PATH="$PATH:/usr/lib/x86_64-linux-gnu/wine"; fi
for t in wine wineserver xdotool python3 go import; do command -v "$t" >/dev/null || { echo "Missing tool: $t" >&2; exit 2; }; done
[[ -f "$ROOT/client/dist/qeukao-client-template.exe" ]] || { echo "先运行 scripts/build_client.sh" >&2; exit 2; }
export WINEPREFIX="$WINEPREFIX_DIR" WINEDEBUG=-all WINEDLLOVERRIDES='mscoree,mshtml=d'
mkdir -p "$HOME/.cache"
LOCK="$WINEPREFIX_DIR.lock"
mkdir "$LOCK" 2>/dev/null || { LOCK=""; echo "另一个全链路 e2e 正在运行" >&2; exit 2; }
if [[ -e "$WINEPREFIX_DIR" ]]; then echo "拒绝复用已存在的 wine 前缀 $WINEPREFIX_DIR" >&2; exit 2; fi
TMP="$(mktemp -d /tmp/qk-full-e2e.XXXXXX)"
mkdir "$TMP/shots"
mkdir "$WINEPREFIX_DIR"; touch "$WINEPREFIX_DIR/.qk-owned"; OWN=1
echo "Xvfb display: $DISPLAY"
timeout 150 wine wineboot -i; wineserver -w
( cd "$ROOT/client" && CGO_ENABLED=0 GOOS=windows GOARCH=amd64 GOPROXY=off GOSUMDB=off go build -trimpath -ldflags "-s -w -H windowsgui" -o "$TMP/fakechrome.exe" ./e2e/fakechrome )

# 端口只在 18000-18999 里挑
PORT="$(python3 - <<'PORTPY'
import random, socket
ports = list(range(18000, 19000)); random.shuffle(ports)
for p in ports:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", p)); print(p); break
        except OSError:
            pass
else:
    raise SystemExit("18000-18999 里没有空闲端口")
PORTPY
)"
# 数据全部落在临时目录：继承来的 QEUKAO_DB / 管理密码 / 会话密钥等环境变量一律清掉或改指向临时目录，
# 否则服务端会去写开发者 shell 里指向的外部库。
unset QEUKAO_DB QEUKAO_ADMIN_PASSWORD QEUKAO_SESSION_SECRET QEUKAO_CLIENT_TEMPLATE QEUKAO_HOST QEUKAO_PORT
export QK_TMP="$TMP" QK_PORT="$PORT" QEUKAO_DATA_DIR="$TMP/data" QEUKAO_DB="$TMP/data/qeukao.sqlite3" QK_SHOTS="$TMP/shots"
export QEUKAO_ADMIN_PASSWORD=112233   # 测试服务用环境变量指定密码，不触发「首次必须改密码」
( cd "$ROOT" && python3 -c "
import os, qk_config
assert str(qk_config.DB_PATH).startswith(os.environ['QK_TMP']), qk_config.DB_PATH
qk_config.save({'backup': {'dir': os.path.join(os.environ['QK_TMP'], 'bk')}})
import app
app.init_all()
s = app.build_server('127.0.0.1', int(os.environ['QK_PORT']))
print('server ready', flush=True)
s.serve_forever()" ) >"$TMP/server.log" 2>&1 &
SERVER_PID=$!
export QEUKAO_CLIENT_NO_INSTALL=1
export QEUKAO_CLIENT_HOME="$(winepath -w "$TMP/home")"
export QEUKAO_CHROME_PATH="$(winepath -w "$TMP/fakechrome.exe")"
export QEUKAO_FAKE_CHROME_LOG="$(winepath -w "$TMP/chrome-urls")"
export QK_CLIENT_HOME_UNIX="$TMP/home"
python3 - <<'PY'
import json, os, subprocess, time, urllib.request, urllib.error, http.cookiejar
from datetime import datetime, timedelta
from pathlib import Path
tmp = Path(os.environ["QK_TMP"]); base = "http://127.0.0.1:%s" % os.environ["QK_PORT"]
jar = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
def call(method, path, body=None, raw=False):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        r = op.open(req, timeout=10); payload = r.read(); code = r.status
    except urllib.error.HTTPError as e:
        payload = e.read(); code = e.code
    return (code, payload) if raw else (code, json.loads(payload.decode()))
def wait(pred, what, secs=60, step=0.4):
    t0 = time.time()
    while time.time() - t0 < secs:
        v = pred()
        if v: return v
        time.sleep(step)
    raise AssertionError("超时：" + what)
def popup():
    r = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", "考务通知"], capture_output=True, text=True)
    return r.stdout.split()[0] if r.returncode == 0 and r.stdout.split() else None
def confirm(win):
    subprocess.run(["xdotool", "keydown", "--window", win, "Return"], check=True)
    subprocess.run(["xdotool", "keyup", "Return"], check=False)
def shot(win, name):
    p = Path(os.environ["QK_SHOTS"]) / ("full-%s-%d.png" % (name, int(time.time())))
    subprocess.run(["import", "-window", win, str(p)], check=True); print("Screenshot:", p, flush=True); return p
def live(): return call("GET", "/api/admin/live")[1]["data"]
steps = []; proc = None
def ok(msg): steps.append(msg); print("OK  " + msg, flush=True)
try:
    wait(lambda: call("GET", "/api/health")[0] == 200, "server health", 30)
    ok("server up on %s" % base)
    c, j = call("POST", "/api/admin/login", {"password": "wrong-one"}); assert c == 401, (c, j); ok("wrong password rejected (401)")
    c, j = call("POST", "/api/admin/login", {"password": "112233"}); assert c == 200 and j["success"], (c, j); ok("default password 112233 logs in")
    d = call("GET", "/api/session")[1]["data"]; assert d["open"] is False and "暂无可填报场次" in d["closedMessage"], d; ok("fresh server: session closed -> '%s'" % d["closedMessage"])
    c, j = call("POST", "/api/current-reports/check-room", {"roomName": "七教室"}); assert c == 409 and j["error"]["code"] == "NO_OPEN_SESSION", (c, j); ok("fill while closed -> 409 NO_OPEN_SESSION")
    c, raw = call("GET", "/api/admin/client/download", raw=True); assert c == 200 and raw[-9:] == b"QKCFG-V1\n", (c, raw[-12:])
    (tmp / "client.exe").write_bytes(raw)
    n = int.from_bytes(raw[-13:-9], "little"); cfg = json.loads(raw[-13 - n:-13].decode())
    assert cfg["v"] == 1 and cfg["enrollKey"], cfg
    ok("downloaded bound client from the server: %d bytes, trailer servers=%s" % (len(raw), cfg["servers"]))
    # 服务端只监听 127.0.0.1，局域网地址在本机不可达：把真实 trailer 里的 servers 换成本次测试地址后再绑定，其余字段(enrollKey/name)保持服务端生成的原值
    cfg["servers"] = [base]; blob = json.dumps(cfg, ensure_ascii=False, separators=(",", ":")).encode()
    tpl = raw[:-13 - n]; (tmp / "client.exe").write_bytes(tpl + blob + len(blob).to_bytes(4, "little") + b"QKCFG-V1\n")
    proc = subprocess.Popen(["wine", str(tmp / "client.exe")], stdout=open(tmp / "client-stdio.log", "w"), stderr=subprocess.STDOUT)
    st = wait(lambda: (lambda L: L if L["clients"] and L["clients"][0]["online"] else None)(live()), "client online on the web board", 90)
    cl = st["clients"][0]; ok("client online on the web board: host=%s ip=%s version=%s" % (cl["name"], cl["ip"], cl["version"]))
    assert popup() is None, "popup must not exist before any dispatch"
    t0 = time.time(); c, j = call("POST", "/api/admin/dispatch", {"mode": "now", "title": "联调场次"}); assert c == 200, (c, j); did = j["data"]["id"]
    win = wait(popup, "popup after immediate dispatch", 30, 0.2); lat = time.time() - t0
    assert lat < 8, lat; ok("immediate dispatch #%d -> popup visible after %.1fs" % (did, lat))
    p1 = shot(win, "now")
    assert call("GET", "/api/session")[1]["data"]["open"] is True; ok("dispatch opened the session")
    confirm(win)
    wait(lambda: (lambda L: L if L["clients"][0]["notice"]["state"] == "opened" else None)(live()), "web board shows opened", 30)
    ok("web board shows client notice state=opened")
    urls = tmp / "chrome-urls"
    wait(lambda: urls.exists() and urls.read_text().strip(), "fake chrome url", 20)
    assert urls.read_text().strip() == base + "/", urls.read_text(); ok("Chrome launched with %s" % urls.read_text().strip())
    wait(lambda: popup() is None, "popup closed after confirm", 10); time.sleep(3)
    assert popup() is None, "popup must not reappear"; ok("popup closed and did not reappear (3s)")
    c, j = call("POST", "/api/current-reports", {"roomName": "七教室", "expectedCount": 45, "actualCount": 43}); assert c == 200, (c, j); ok("room 7 submitted 45/43 while open")
    L = wait(lambda: (lambda L: L if L["summary"]["roomsSubmitted"] == 1 else None)(live()), "board shows submission", 15)
    r7 = [r for r in L["rooms"] if r["roomNumber"] == 7][0]; assert r7["submitted"] and r7["report"]["absentCount"] == 2, r7
    ok("admin board shows room 7: absent=2 rate=%s" % r7["report"]["attendanceRate"])
    c, j = call("POST", "/api/current-reports", {"roomName": "七教室", "expectedCount": 45, "actualCount": 44}); assert c == 409 and j["error"]["code"] == "PENDING_ACCEPTANCE", (c, j)
    ok("second fill of the same room blocked (PENDING_ACCEPTANCE) - original rule intact")
    c, j = call("POST", "/api/reports/accept", {"password": "112233"}); assert c in (401, 404), (c, j); ok("old front-page accept path is gone")
    c, j = call("POST", "/api/admin/accept", {}); assert c in (200, 201), (c, j); ok("accepted (admin session, no password re-typed)")
    assert call("GET", "/api/session")[1]["data"]["open"] is False; ok("after accept: session closed")
    c, j = call("POST", "/api/current-reports", {"roomName": "八教室", "expectedCount": 40, "actualCount": 40})
    assert c == 409 and j["error"]["code"] == "NO_OPEN_SESSION" and "暂无可填报场次" in j["error"]["message"], (c, j); ok("after accept: fill -> 409 '%s'" % j["error"]["message"])
    st = live()["serverTime"]
    due = (datetime.fromisoformat(st).replace(tzinfo=None) + timedelta(seconds=7)).strftime("%Y-%m-%dT%H:%M:%S")
    c, j = call("POST", "/api/admin/dispatch", {"mode": "scheduled", "title": "联调场次二", "scheduledAt": due, "message": "下午场：请点击确定填写缺考信息"})
    assert c == 200 and j["data"]["status"] == "pending", (c, j); sid = j["data"]["id"]; ok("scheduled dispatch #%d for %s (server time) is pending" % (sid, due))
    assert popup() is None
    past = (datetime.fromisoformat(st).replace(tzinfo=None) - timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%S")
    c, j = call("POST", "/api/admin/dispatch", {"mode": "scheduled", "title": "联调", "scheduledAt": past}); assert c == 400, (c, j); ok("scheduled time in the past rejected (400)")
    win = wait(popup, "popup at the scheduled time", 40, 0.2)
    late = (datetime.now() - datetime.fromisoformat(due)).total_seconds()
    assert -1 <= late < 8, late; ok("scheduled popup appeared %.1fs after the due time" % late)
    p2 = shot(win, "scheduled"); assert call("GET", "/api/session")[1]["data"]["open"] is True; ok("scheduled dispatch re-opened the session")
    confirm(win); wait(lambda: popup() is None, "popup closed", 10)
    wait(lambda: next((x for x in live()["dispatches"] if x["id"] == sid), {}).get("counts", {}).get("opened", 0) >= 1, "dispatch counts.opened", 20)
    wait(lambda: len(urls.read_text().split()) >= 2, "second Chrome launch recorded", 20)
    got = urls.read_text().split(); assert got == [base + "/", base + "/"], got
    ok("dispatch #%d counts.opened>=1; Chrome launched twice in total (once per confirmed dispatch): %s" % (sid, got))
    # 最难排版的合法文案：200 个连续宽字母（英文按词折行）、200 个汉字、9 个短行；每条都真弹窗、真确认，
    # 然后断言客户端用真实 DrawText 度量得到的结果是「放得下」。
    hard = {"200 个 W": "W" * 200, "200 个汉字": "缺考" * 100, "9 个短行": "\n".join(["行"] * 9), "词间空格的英文": ("WWWWWWWWWW " * 18) + "WW",
            "长数字串": "1234567890" * 20, "长 URL": "https://school.example.edu/notice/" + "20261025" * 20,
            "200 个 é": "é" * 200, "30 个 emoji": "\U0001F600" * 30,
            "9 行各 15 个 emoji": "\n".join(["\U0001F600" * 15] * 9)}
    for label, msg in hard.items():
        c, j = call("POST", "/api/admin/dispatch", {"mode": "now", "title": "联调", "message": msg}); assert c == 200, (label, c, j)
        win = wait(popup, "popup for " + label, 30, 0.2); time.sleep(0.4); confirm(win); wait(lambda: popup() is None, "popup closed " + label, 10)
        # 布局日志在弹窗创建前写入：此刻日志里最后一条 popup: layout 就是这条文案的——逐条断言，不让「A 放得下、B 放不下」互相抵消
        lay = [l for l in (Path(os.environ["QK_CLIENT_HOME_UNIX"]) / "client.log").read_text().splitlines() if "popup: layout" in l]
        assert lay and "measured-fits=true" in lay[-1], "文案 [%s] 的真实度量说放不下：%s" % (label, lay[-1:] )
        ok("hard message [%s] popped up, confirmed, real DrawText measurement says it fits (%s)" % (label, lay[-1].split("popup: ")[1]))
    log = (Path(os.environ["QK_CLIENT_HOME_UNIX"]) / "client.log").read_text(); assert "tray: icon added" in log, log; ok("client log: tray icon added")
    layouts = [l for l in log.splitlines() if "popup: layout" in l]
    assert len(layouts) >= 6, layouts
    # 所有最难的合法文案（含没有空格的 200 个 W、长数字串、长 URL）都必须被真实 DrawText 度量判定为放得下，不许有 WARNING
    bad = [l for l in layouts if "measured-fits=true" not in l]
    warnings = [l for l in log.splitlines() if "WARNING text does not fully fit" in l]
    assert not bad and not warnings, "客户端自己的真实度量说放不下：%s %s" % (bad, warnings)
    ok("all %d popups fit by real DrawText measurement (incl. 200 W, long digits, long URL), e.g. %s" % (len(layouts), layouts[-1].split("popup: ")[1]))
    keep = os.environ.get("QK_KEEP_SHOTS")
    if keep:
        import shutil; Path(keep).mkdir(parents=True, exist_ok=True)
        for p in (p1, p2): shutil.copy2(p, keep)
        print("screenshots kept in", keep)
    print("\nPASS: %d checks" % len(steps))
except Exception:
    for p in (tmp / "server.log", Path(os.environ["QK_CLIENT_HOME_UNIX"]) / "client.log", tmp / "client-stdio.log"):
        if p.exists(): print("Diagnostic %s:\n%s" % (p, p.read_text(errors="replace")[-3000:]), flush=True)
    raise
finally:
    if proc is not None:
        try: proc.terminate()
        except Exception: pass
PY