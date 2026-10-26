#!/usr/bin/env python3
"""Independent contract §5.2 server for the real Wine executable (stdlib only)."""
from __future__ import annotations

import argparse
import datetime
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.fire = threading.Event()
        self.acks = []
        self.clients = set()
        self.served = set()


STATE = State()


def server_time():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec="seconds")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_json(self, data, status=200, code=""):
        if status == 200:
            payload = {"success": True, "data": data}
        else:
            payload = {"success": False, "error": {"code": code, "message": code}}
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def handle_request(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        if path == "/_test/fire":
            STATE.fire.set()
            return self.send_json({"fired": True})
        if path == "/_test/acks":
            with STATE.lock:
                return self.send_json({"acks": list(STATE.acks), "clients": len(STATE.clients)})
        if self.headers.get("X-Qk-Key") != "wine-test-enrollment":
            return self.send_json(None, 401, "UNAUTHORIZED")
        body = {}
        if self.command == "POST":
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size > 65536:
                    raise ValueError("body too large")
                body = json.loads(self.rfile.read(size))
            except (ValueError, UnicodeError):
                return self.send_json(None, 400, "BAD_REQUEST")
        if path == "/api/agent/hello" and self.command == "POST":
            client_id = body.get("clientId", "")
            if not isinstance(client_id, str) or not 8 <= len(client_id) <= 64:
                return self.send_json(None, 400, "BAD_REQUEST")
            if not all(name in body for name in ("hostname", "version", "localIps")):
                return self.send_json(None, 400, "BAD_REQUEST")
            with STATE.lock:
                STATE.clients.add(client_id)
            return self.send_json({"serverTime": server_time(), "serverName": "Wine 契约测试", "pollSeconds": 25,
                                   "room": {"matched": False, "roomName": "", "roomNumber": None}})
        if path == "/api/agent/poll" and self.command == "GET":
            query = parse_qs(parsed.query)
            client_id = query.get("clientId", [""])[0]
            with STATE.lock:
                known = client_id in STATE.clients
            if not known or query.get("wait") != ["25"]:
                return self.send_json(None, 400, "BAD_REQUEST")
            STATE.fire.wait(25)
            notice = None
            with STATE.lock:
                if STATE.fire.is_set() and client_id not in STATE.served:
                    STATE.served.add(client_id)
                    notice = {"dispatchId": 1, "title": "测试考试", "message": "请点击确定填写缺考信息", "openPath": "/"}
            if notice is None:
                threading.Event().wait(0.5)
            return self.send_json({"serverTime": server_time(), "session": {"open": STATE.fire.is_set()}, "notice": notice})
        if path == "/api/agent/ack" and self.command == "POST":
            if body.get("state") not in ("shown", "confirmed", "opened", "failed") or body.get("dispatchId") != 1:
                return self.send_json(None, 400, "BAD_REQUEST")
            with STATE.lock:
                if body.get("clientId") not in STATE.clients:
                    return self.send_json(None, 400, "BAD_REQUEST")
                STATE.acks.append(body)
            return self.send_json({"ok": True})
        return self.send_json(None, 404, "NOT_FOUND")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ready-file", required=True)
    args = parser.parse_args()
    server = None
    for port in range(18000, 19000):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if server is None:
        raise RuntimeError("no unused independent port in 18000..18999")
    Path(args.ready_file).write_text(str(server.server_port), encoding="utf-8")
    print("Stub server: http://127.0.0.1:%s" % server.server_port, flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
