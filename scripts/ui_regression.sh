#!/usr/bin/env bash
# 前端回归检查：临时数据目录 + 临时 DB + 18000-18999 内的端口起真实服务端，
# xvfb-run -a 下用无头浏览器跑 scripts/ui_regression.cjs。
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
TMP=""; SPID=""; SPID2=""
cleanup() { if [[ -n "$SPID" ]]; then kill "$SPID" 2>/dev/null || true; fi; if [[ -n "$SPID2" ]]; then kill "$SPID2" 2>/dev/null || true; fi; if [[ -n "$TMP" && "$TMP" == /tmp/qk-uireg.* ]]; then rm -rf -- "$TMP"; fi; }
trap cleanup EXIT   # 先注册清理，再获取资源
TMP="$(mktemp -d /tmp/qk-uireg.XXXXXX)"
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
cd "$ROOT"
# 继承来的 QEUKAO_DB / 密码 / 密钥等一律清掉，数据全部落临时目录
unset QEUKAO_DB QEUKAO_ADMIN_PASSWORD QEUKAO_SESSION_SECRET QEUKAO_CLIENT_TEMPLATE QEUKAO_HOST QEUKAO_PORT
export QEUKAO_DATA_DIR="$TMP/data" QEUKAO_DB="$TMP/data/qeukao.sqlite3" QK_PORT="$PORT" QK_TMP="$TMP"
export QEUKAO_ADMIN_PASSWORD=112233   # 测试服务用环境变量指定密码，不触发「首次必须改密码」；首次改密码页面单独测
python3 -c "
import os, qk_config
assert str(qk_config.DB_PATH).startswith(os.environ['QK_TMP']), qk_config.DB_PATH
qk_config.save({'backup': {'enabled': False, 'dir': os.path.join(os.environ['QK_TMP'], 'bk')}})
import app; app.init_all(); app.build_server('127.0.0.1', int(os.environ['QK_PORT'])).serve_forever()" >"$TMP/server.log" 2>&1 &
SPID=$!
for _ in $(seq 1 50); do curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && break; sleep 0.2; done
: "${CHROME:=$(ls "$HOME"/.cache/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell 2>/dev/null | tail -1)}"
: "${PLAYWRIGHT_PATH:=$(npm root -g)/playwright}"
# 第二个服务端：全新数据目录、没有环境变量密码，用来测「首次使用必须先改密码」
PORT2="$(python3 - <<'PORTPY'
import random, socket
ports = list(range(18000, 19000)); random.shuffle(ports)
for p in ports:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", p)); print(p); break
        except OSError:
            pass
PORTPY
)"
( unset QEUKAO_ADMIN_PASSWORD QEUKAO_DB; export QEUKAO_DATA_DIR="$TMP/data2" QK_PORT2="$PORT2"; python3 -c "
import os, qk_config
qk_config.save({'backup': {'enabled': False, 'dir': os.path.join(os.environ['QK_TMP'], 'bk2')}})
import app; app.init_all(); app.build_server('127.0.0.1', int(os.environ['QK_PORT2'])).serve_forever()" ) >"$TMP/server2.log" 2>&1 &
SPID2=$!
for _ in $(seq 1 50); do curl -fsS "http://127.0.0.1:$PORT2/api/health" >/dev/null 2>&1 && break; sleep 0.2; done
export CHROME PLAYWRIGHT_PATH BASE="http://127.0.0.1:$PORT" FIRST_RUN_BASE="http://127.0.0.1:$PORT2"
xvfb-run -a node scripts/ui_regression.cjs
