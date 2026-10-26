package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

// newRangedServer 起一个只监听 18000-18999（契约 §0：测试一律独立端口段）的 httptest 服务端，避免系统随机端口撞上别的服务。
func newRangedServer(t *testing.T, h http.Handler) *httptest.Server {
	t.Helper()
	for port := 18000; port < 19000; port++ {
		l, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", port))
		if err != nil {
			continue
		}
		// 不用 httptest.NewUnstartedServer：它会先在系统随机端口上建一个监听再换掉，字面上违反「测试一律 18000–18999」
		s := &httptest.Server{Listener: l, Config: &http.Server{Handler: h}}
		s.Start()
		return s
	}
	t.Fatal("no independent test port available in 18000-18999")
	return nil
}

// 假服务端：记录每条回执的 state，ackStatus 控制返回码。
type ackLog struct {
	mu     sync.Mutex
	states []string
	status int
}

func (l *ackLog) handler(w http.ResponseWriter, r *http.Request) {
	var body struct{ State string }
	json.NewDecoder(r.Body).Decode(&body)
	l.mu.Lock()
	l.states = append(l.states, body.State)
	status := l.status
	l.mu.Unlock()
	w.Header().Set("Content-Type", "application/json")
	if status != 0 && status != 200 {
		w.WriteHeader(status)
		w.Write([]byte(`{"success":false,"error":{"code":"X","message":"no"}}`))
		return
	}
	w.Write([]byte(`{"success":true,"data":{"ok":true}}`))
}
func (l *ackLog) seen() []string {
	l.mu.Lock()
	defer l.mu.Unlock()
	return append([]string(nil), l.states...)
}

// presentNotice 跑一遍真实的完成分支：窗口立即「确认」，浏览器启动结果可控。
func runPresent(t *testing.T, launch func() (string, error)) (*NoticeState, []string) {
	t.Helper()
	logs := &ackLog{}
	srv := newRangedServer(t, http.HandlerFunc(logs.handler))
	defer srv.Close()
	agent := NewAgent(Config{V: 1, Servers: []string{srv.URL}, EnrollKey: "k"}, "0123456789abcdef")
	oldUI, oldOpen := showNoticeUI, openBrowser
	defer func() { showNoticeUI, openBrowser = oldUI, oldOpen }()
	showNoticeUI = func(_ string, shown, confirmed func()) error { shown(); confirmed(); return nil }
	openBrowser = func(string, string) (string, error) { return launch() }
	var state NoticeState
	n := &Notice{DispatchID: 5, Message: "m", OpenPath: "/", Server: srv.URL}
	state.Receive(n)
	presentNotice(agent, &state, n)
	return &state, logs.seen()
}

func TestPresentOpenedIsFinalAndNotRepeated(t *testing.T) {
	state, acks := runPresent(t, func() (string, error) { return "", nil })
	if strings.Join(acks, ",") != "shown,confirmed,opened" {
		t.Fatalf("acks=%v", acks)
	}
	if state.Receive(&Notice{DispatchID: 5}) {
		t.Fatal("opened notice popped up again")
	}
}

// 没找到 Chrome、改用默认浏览器：回执是 failed(detail)，但页面已经打开了——不能重弹。
func TestPresentDefaultBrowserFallbackIsHandled(t *testing.T) {
	state, acks := runPresent(t, func() (string, error) { return "chrome-not-found,used-default-browser", nil })
	if strings.Join(acks, ",") != "shown,confirmed,failed" {
		t.Fatalf("acks=%v", acks)
	}
	if state.Receive(&Notice{DispatchID: 5}) {
		t.Fatal("page was opened via the default browser, must not pop up again")
	}
}

// 真正启动失败：回执 failed，允许重弹（有上限）。
func TestPresentLaunchErrorMayPopAgain(t *testing.T) {
	state, acks := runPresent(t, func() (string, error) { return "", errors.New("blocked by policy") })
	if strings.Join(acks, ",") != "shown,confirmed,failed" {
		t.Fatalf("acks=%v", acks)
	}
	if !state.Receive(&Notice{DispatchID: 5}) {
		t.Fatal("a real launch failure must be offered again")
	}
}

// ack 对永久性错误不能无限重试：服务端回 404（通知记录被导入的库覆盖了）就该放弃，状态机继续往下走。
func TestAckGivesUpOnPermanentRefusal(t *testing.T) {
	logs := &ackLog{status: 404}
	srv := newRangedServer(t, http.HandlerFunc(logs.handler))
	defer srv.Close()
	agent := NewAgent(Config{V: 1, Servers: []string{srv.URL}, EnrollKey: "k"}, "0123456789abcdef")
	done := make(chan bool, 1)
	go func() { done <- ackUntilSent(agent, &Notice{DispatchID: 1, Server: srv.URL}, "shown", "") }()
	select {
	case ok := <-done:
		if ok {
			t.Fatal("a refused ack reported success")
		}
	case <-time.After(5 * time.Second):
		t.Fatal("ack retried a permanent 404 forever")
	}
	if n := len(logs.seen()); n != 1 {
		t.Fatalf("permanent refusal retried %d times", n)
	}
}

// 暂时性错误会重试，但总时间有上限（这里把上限缩到 1 秒验证出口存在）。
func TestAckStopsAfterTheTimeLimit(t *testing.T) {
	logs := &ackLog{status: 503}
	srv := newRangedServer(t, http.HandlerFunc(logs.handler))
	defer srv.Close()
	agent := NewAgent(Config{V: 1, Servers: []string{srv.URL}, EnrollKey: "k"}, "0123456789abcdef")
	old := ackQuickLimit
	ackQuickLimit = time.Second
	defer func() { ackQuickLimit = old }()
	done := make(chan bool, 1)
	go func() { done <- ackUntilSent(agent, &Notice{DispatchID: 1, Server: srv.URL}, "shown", "") }()
	select {
	case ok := <-done:
		if ok {
			t.Fatal("503 ack reported success")
		}
	case <-time.After(10 * time.Second):
		t.Fatal("ack never gave up on a persistent 503")
	}
}

// 回执发往「当前」服务端：通知当初来自的地址失效、轮询已换到别的地址时不能再往死地址发。
func TestAckUsesTheCurrentServerNotTheNoticesOriginalOne(t *testing.T) {
	logs := &ackLog{}
	live := newRangedServer(t, http.HandlerFunc(logs.handler))
	defer live.Close()
	agent := NewAgent(Config{V: 1, Servers: []string{"http://127.0.0.1:1", live.URL}, EnrollKey: "k"}, "0123456789abcdef")
	agent.rotate() // 轮询已经换到 live
	if !ackUntilSent(agent, &Notice{DispatchID: 1, Server: "http://127.0.0.1:1"}, "shown", "") {
		t.Fatal("ack should have gone to the current server")
	}
}

// client-id 文件为空/损坏（断电留下 0 字节）：重新生成并写好，不能让 worker 永远起不来。
func TestClientIDRecoversFromAnEmptyOrCorruptFile(t *testing.T) {
	for _, content := range []string{"", "not-hex", "abcd"} {
		home := t.TempDir()
		if err := os.WriteFile(filepath.Join(home, "client-id"), []byte(content), 0600); err != nil {
			t.Fatal(err)
		}
		id, err := clientID(home)
		if err != nil || len(id) != 32 {
			t.Fatalf("content %q: id=%q err=%v", content, id, err)
		}
		again, _ := clientID(home)
		if again != id {
			t.Fatalf("regenerated id was not persisted: %q vs %q", id, again)
		}
	}
}

// 弹窗收到的文案必须已经规范化换行：度量（DrawText）和绘制用的是同一份文字，旧库里的历史文案或手工写入的数据
// 带着 CR / U+2028 等也不能让排版算出另一个行数。
func TestPopupReceivesNormalizedLineBreaks(t *testing.T) {
	logs := &ackLog{}
	srv := newRangedServer(t, http.HandlerFunc(logs.handler))
	defer srv.Close()
	agent := NewAgent(Config{V: 1, Servers: []string{srv.URL}, EnrollKey: "k"}, "0123456789abcdef")
	oldUI, oldOpen := showNoticeUI, openBrowser
	defer func() { showNoticeUI, openBrowser = oldUI, oldOpen }()
	var got string
	showNoticeUI = func(body string, shown, confirmed func()) error { got = body; shown(); confirmed(); return nil }
	openBrowser = func(string, string) (string, error) { return "", nil }
	var state NoticeState
	n := &Notice{DispatchID: 6, Message: "甲\r乙\r\n丙\u2028丁\x0b戊", OpenPath: "/", Server: srv.URL}
	state.Receive(n)
	presentNotice(agent, &state, n)
	if got != "甲\n乙\n丙\n丁\n戊" {
		t.Fatalf("popup got un-normalized text: %q", got)
	}
}
