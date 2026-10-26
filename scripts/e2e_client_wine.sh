#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
if [[ "$#" == 0 ]]; then
  exec xvfb-run -a -s '-screen 0 1440x900x24' "$0" --inside-xvfb
fi
[[ "${1:-}" == --inside-xvfb && -n "${DISPLAY:-}" ]] || exit 2
# 不能只靠 DISPLAY 字符串判断（:1、:0.0 照样是真实桌面）：必须确认自己确实是 xvfb-run 的后代。
pid=$$; under_xvfb_run=0
while [[ "$pid" -gt 1 ]]; do
  if tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q 'xvfb-run'; then under_xvfb_run=1; break; fi
  pid="$(ps -o ppid= -p "$pid" | tr -d ' ')"
done
[[ "$under_xvfb_run" == 1 ]] || { echo "拒绝运行：当前进程不在 xvfb-run 之下，DISPLAY=${DISPLAY:-} 可能是真实桌面" >&2; exit 2; }
if ! command -v wineserver >/dev/null && [[ -x /usr/lib/x86_64-linux-gnu/wine/wineserver ]]; then
  export PATH="$PATH:/usr/lib/x86_64-linux-gnu/wine"
fi
for tool in wine wineserver xdotool python3 go; do command -v "$tool" >/dev/null || { echo "Missing tool: $tool" >&2; exit 2; }; done
export WINEPREFIX="$HOME/.cache/qk-client-wine"
export WINEDEBUG=-all WINEDLLOVERRIDES='mscoree,mshtml=d'
PREFIX_EXPECTED="$HOME/.cache/qk-client-wine"
LOCK="$WINEPREFIX.e2e-lock"
mkdir -p "$HOME/.cache" /tmp/qk-e2e
if ! mkdir "$LOCK"; then echo 'Another qk Wine e2e owns the prefix lock' >&2; exit 2; fi
if [[ -e "$WINEPREFIX" ]]; then rmdir "$LOCK"; echo "Refusing existing Wine prefix: $WINEPREFIX" >&2; exit 2; fi
TMP="$(mktemp -d /tmp/qk-client-e2e.XXXXXX)"
export QEUKAO_DATA_DIR="$TMP/data"
SERVER_PID='' CLIENT_PID='' OWN_PREFIX=0 OWN_FAKE_CHROME=0
FAKE_CHROME="$ROOT/client/e2e/fakechrome.exe"
if [[ -e "$FAKE_CHROME" ]]; then echo "Refusing existing test executable: $FAKE_CHROME" >&2; rmdir "$LOCK"; rmdir "$TMP"; exit 2; fi
cleanup() {
  status=$?
  trap - EXIT INT TERM
  if [[ -n "$CLIENT_PID" ]]; then kill "$CLIENT_PID" 2>/dev/null || true; wait "$CLIENT_PID" 2>/dev/null || true; fi
  if [[ -n "$SERVER_PID" ]]; then kill "$SERVER_PID" 2>/dev/null || true; wait "$SERVER_PID" 2>/dev/null || true; fi
  # Only this run may stop this prefix; never touch another session's wineserver.
  if [[ "$OWN_PREFIX" == 1 && "$WINEPREFIX" == "$PREFIX_EXPECTED" && -f "$WINEPREFIX/.qk-e2e-owned" ]]; then
    printf 'Cleanup owned Wine prefix: %s\n' "$WINEPREFIX"
    wineserver -k || true
    wineserver -w || true
    rm -rf -- "$WINEPREFIX"
  fi
  if [[ "$OWN_FAKE_CHROME" == 1 && "$FAKE_CHROME" == "$ROOT/client/e2e/fakechrome.exe" ]]; then rm -f -- "$FAKE_CHROME"; fi
  if [[ "$TMP" == /tmp/qk-client-e2e.* && -d "$TMP" ]]; then rm -rf -- "$TMP"; fi
  rmdir "$LOCK"
  exit "$status"
}
trap cleanup EXIT INT TERM
mkdir "$WINEPREFIX"
touch "$WINEPREFIX/.qk-e2e-owned"
OWN_PREFIX=1
printf 'Xvfb display: %s\n' "$DISPLAY"
timeout 120 wine wineboot -i
wineserver -w
cd "$ROOT/client"
OWN_FAKE_CHROME=1
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 GOPROXY=off GOSUMDB=off \
  go build -trimpath -ldflags "-s -w -H windowsgui" -o "$FAKE_CHROME" ./e2e/fakechrome
python3 e2e/stub_server.py --ready-file "$TMP/port" >"$TMP/server.log" 2>&1 &
SERVER_PID=$!
export QK_E2E_TMP="$TMP"
python3 - <<'PY'
import os, time
from pathlib import Path
ready = Path(os.environ["QK_E2E_TMP"]) / "port"
for _ in range(100):
    if ready.exists():
        break
    time.sleep(0.1)
else:
    raise SystemExit("stub server did not start")
PY
PORT="$(python3 -c 'import os,pathlib; print((pathlib.Path(os.environ["QK_E2E_TMP"])/"port").read_text())')"
export QK_E2E_URL="http://127.0.0.1:$PORT"
# Bind the actual template, exercising trailer parsing rather than only CLI mode.
python3 - <<'PY'
import json, os, struct
from pathlib import Path
root = Path(os.environ["QK_E2E_TMP"])
payload = json.dumps({"v": 1, "servers": [os.environ["QK_E2E_URL"]],
                      "enrollKey": "wine-test-enrollment", "name": "Wine test"}).encode()
(root / "client.exe").write_bytes(Path("dist/qeukao-client-template.exe").read_bytes() + payload + struct.pack("<I", len(payload)) + b"QKCFG-V1\n")
PY
export QEUKAO_CLIENT_NO_INSTALL=1
export QEUKAO_CLIENT_HOME="$(winepath -w "$TMP/home")"
export QEUKAO_CHROME_PATH="$(winepath -w "$FAKE_CHROME")"
export QEUKAO_FAKE_CHROME_LOG="$(winepath -w "$TMP/chrome-urls")"
wine "$TMP/client.exe" >"$TMP/client-stdio.log" 2>&1 &
CLIENT_PID=$!
python3 - <<'PY'
import json, os, shutil, subprocess, time
from pathlib import Path
from urllib.request import urlopen

root = Path(os.environ["QK_E2E_TMP"])
base = os.environ["QK_E2E_URL"]

def get(path):
    with urlopen(base + path, timeout=3) as response:
        return json.load(response)["data"]

try:
    for _ in range(180):
        if get("/_test/acks")["clients"]:
            break
        time.sleep(0.5)
    else:
        raise AssertionError("Windows client did not hello")
    print("Protocol: hello accepted", flush=True)
    get("/_test/fire")
    window = None
    for _ in range(120):
        found = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", "考务通知"], capture_output=True, text=True)
        if found.returncode == 0:
            window = found.stdout.splitlines()[0]
            break
        time.sleep(0.5)
    assert window, "no visible 考务通知 window"
    # The window must ignore Alt+F4/WM_CLOSE; take evidence after sending it.
    subprocess.run(["xdotool", "key", "--window", window, "alt+F4"], check=True)
    time.sleep(0.3)
    subprocess.run(["xdotool", "getwindowname", window], check=True)
    screenshot = Path("/tmp/qk-e2e") / ("popup-" + str(int(time.time())) + ".png")
    if shutil.which("import"):
        subprocess.run(["import", "-window", window, str(screenshot)], check=True)
    else:
        xwd = root / "popup.xwd"
        subprocess.run(["xwd", "-silent", "-id", window, "-out", str(xwd)], check=True)
        subprocess.run(["convert", str(xwd), str(screenshot)], check=True)
    print("Screenshot: " + str(screenshot), flush=True)
    # Return destroys the window synchronously; do not send key-up to its stale XID.
    subprocess.run(["xdotool", "keydown", "--window", window, "Return"], check=True)
    subprocess.run(["xdotool", "keyup", "Return"], check=True)
    for _ in range(120):
        acks = get("/_test/acks")["acks"]
        states = [ack["state"] for ack in acks]
        if len(states) >= 3:
            break
        time.sleep(0.5)
    assert states[:2] == ["shown", "confirmed"] and states[2:] in (["opened"], ["failed"]), states
    print("ACK sequence: " + " -> ".join(states), flush=True)
    print("ACK JSON: " + json.dumps(acks, ensure_ascii=False), flush=True)
    for _ in range(80):
        urls = root / "chrome-urls"
        if urls.exists() and urls.read_text().strip():
            break
        time.sleep(0.25)
    else:
        raise AssertionError("fake Chrome did not receive URL")
    assert urls.read_text().strip() == base + "/", urls.read_text()
    assert states[-1] == "opened", acks
    print("Chrome URL: " + urls.read_text().strip(), flush=True)
    log = (root / "home" / "client.log").read_text()
    assert "tray: icon added " in log, log
    print("Client log:\n" + log, end="", flush=True)
    print("PASS: Wine popup, confirmation, ACKs and fake Chrome URL", flush=True)
except Exception:
    for path in (root / "client-stdio.log", root / "home" / "client.log", root / "server.log"):
        if path.exists():
            print("Diagnostic " + str(path) + ":\n" + path.read_text(errors="replace")[-6000:], flush=True)
    raise
PY
