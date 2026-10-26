package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"flag"
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

func clientHome() string {
	if home := os.Getenv("QEUKAO_CLIENT_HOME"); home != "" {
		return home
	}
	return filepath.Join(os.Getenv("LOCALAPPDATA"), "QeukaoClient")
}

type rotatingLog struct {
	mu   sync.Mutex
	path string
}

func (w *rotatingLog) Write(p []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	if info, err := os.Stat(w.path); err == nil && info.Size() > 1<<20 {
		if err := os.Rename(w.path, w.path+".1"); err != nil {
			return 0, err
		}
	}
	f, err := os.OpenFile(w.path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0600)
	if err != nil {
		return 0, err
	}
	defer f.Close()
	return f.Write(p)
}

// clientID 读取持久化的客户端标识；文件不存在、为空或损坏（断电造成的 0 字节文件）都重新生成并原子写入，
// 绝不能因为它启动失败——否则监护会无限重启一个永远起不来的 worker。
func clientID(home string) (string, error) {
	path := filepath.Join(home, "client-id")
	data, err := os.ReadFile(path)
	if err == nil {
		id := strings.TrimSpace(string(data))
		if decoded, e := hex.DecodeString(id); e == nil && len(decoded) == 16 {
			return id, nil
		}
		log.Printf("client-id: persisted value invalid, regenerating")
	} else if !os.IsNotExist(err) {
		return "", err
	}
	var raw [16]byte
	if _, err := rand.Read(raw[:]); err != nil {
		return "", err
	}
	id := hex.EncodeToString(raw[:])
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, []byte(id), 0600); err != nil {
		return "", err
	}
	if err := os.Rename(tmp, path); err != nil {
		os.Remove(tmp)
		return "", err
	}
	return id, nil
}
func main() {
	server := flag.String("server", "", "development server URL")
	key := flag.String("key", "", "development enrollment key")
	worker := flag.Bool("worker", false, "run worker process")
	noGuard := flag.Bool("no-guard", false, "run worker without supervisor")
	installed := flag.Bool("installed", false, "started by the install step: skip installing again")
	flag.Parse()
	home := clientHome()
	if err := os.MkdirAll(home, 0700); err != nil {
		return
	}
	log.SetOutput(&rotatingLog{path: filepath.Join(home, "client.log")})
	log.SetFlags(log.Ldate | log.Ltime)
	// Guard panics must never produce an interactive Windows error dialog.
	defer func() {
		if p := recover(); p != nil {
			log.Printf("panic: %v", p)
			os.Exit(1)
		}
	}()
	cfg, err := loadConfig(*server, *key)
	if err != nil {
		log.Printf("config: %v", err)
		return
	}
	if !*worker && !*noGuard {
		if !*installed {
			// 安装失败（目录不可写、Run 键被安全软件拦）不能让客户端整个不运行：记日志后就地运行。
			done, err := installSelf()
			if err != nil {
				log.Printf("install: %v (running from the current location)", err)
			}
			if done {
				return
			}
		}
		release, ok := singleInstance("Guard")
		if !ok {
			return
		}
		defer release()
		supervise()
		return
	}
	release, ok := singleInstance("Worker")
	if !ok {
		os.Exit(exitAlreadyRunning) // 不能返回 0：0 会让监护以为用户选择了退出
	}
	defer release()
	id, err := clientID(home)
	if err != nil {
		log.Printf("client-id: %v", err)
		os.Exit(1)
	}
	go runWorker(NewAgent(*cfg, id))
	runTray()
}
func supervise() {
	exe, err := os.Executable()
	if err != nil {
		log.Printf("guard executable: %v", err)
		return
	}
	args := append([]string{"--worker"}, os.Args[1:]...)
	var policy GuardianPolicy
	run := func() int {
		cmd := exec.Command(exe, args...)
		hideProcess(cmd)
		if err := cmd.Run(); err != nil {
			if cmd.ProcessState != nil {
				return cmd.ProcessState.ExitCode()
			}
			return 1
		}
		return 0
	}
	for {
		delay, restart := superviseOnce(run, &policy)
		if !restart {
			return
		}
		time.Sleep(delay)
	}
}

// superviseOnce 跑一次 worker 并决定是否重启。里面任何 panic 都只当作 worker 异常退出：
// 监护进程自己不能死（契约 §7），否则之后没有人重启 worker。
func superviseOnce(run func() int, policy *GuardianPolicy) (delay time.Duration, restart bool) {
	defer func() {
		if p := recover(); p != nil {
			log.Printf("guard: recovered panic: %v", p)
			delay, restart = 30*time.Second, true
		}
	}()
	started := time.Now()
	code := run()
	delay, restart = policy.Exited(code, time.Since(started))
	if restart {
		log.Printf("guard: worker exit=%d restart in %s", code, delay)
	}
	return
}
func retryDelay(err error, b *Backoff) time.Duration {
	var api *APIError
	if errors.As(err, &api) && (api.Status == 401 || api.Status == 403) {
		return 30 * time.Second
	}
	return b.Next()
}
func runWorker(a *Agent) {
	var notices NoticeState
	var retry Backoff
	connected := false
	ctx := context.Background()
	for {
		if !connected {
			if err := a.Connect(ctx); err != nil {
				setTrayConnected(false)
				log.Printf("hello: %v", err)
				time.Sleep(retryDelay(err, &retry))
				continue
			}
			connected = true
			setTrayConnected(true)
			log.Printf("agent: connected")
		}
		n, err := a.Poll(ctx)
		if err != nil {
			setTrayConnected(false)
			log.Printf("poll: %v", err)
			// 不在这里 rotate：Connect 从当前地址开始，失败才逐个换，所以一次网络抖动先重试原地址。
			connected = false
			time.Sleep(retryDelay(err, &retry))
			continue
		}
		retry.Reset()
		if n == nil || n.DispatchID <= 0 {
			continue
		}
		if notices.Receive(n) {
			go presentNotice(a, &notices, n)
			time.Sleep(500 * time.Millisecond)
			continue
		}
		// 弹窗已在显示或这条已处理：服务端会立刻返回同一条，放慢到 2 秒一轮，别让几十台机器空转打满服务端。
		time.Sleep(2 * time.Second)
	}
}

// 回执重试的上限。shown/confirmed 卡着老师的点击流程，所以短；opened/failed 只是汇报，可以久一点。
var (
	ackQuickLimit = 30 * time.Second
	ackFinalLimit = 5 * time.Minute
)

// ackUntilSent 重试到服务端收下为止，但有三个出口：成功；服务端明确拒绝（除 401/403/408/429 外的 4xx，
// 例如通知记录已被导入的库覆盖掉 → 404，重试一万次也不会成功）；超过时间上限。绝不能无限阻塞弹窗状态机。
func ackUntilSent(a *Agent, n *Notice, state, detail string) bool {
	limit := ackQuickLimit
	if state == "opened" || state == "failed" {
		limit = ackFinalLimit
	}
	deadline := time.Now().Add(limit)
	var retry Backoff
	for {
		err := a.Ack(context.Background(), n, state, detail)
		if err == nil {
			log.Printf("ack: dispatch=%d state=%s", n.DispatchID, state)
			return true
		}
		var api *APIError
		if errors.As(err, &api) && api.Status >= 400 && api.Status < 500 && api.Status != 401 && api.Status != 403 && api.Status != 408 && api.Status != 429 {
			log.Printf("ack %d %s: server refused (%v), giving up", n.DispatchID, state, err)
			return false
		}
		if !time.Now().Before(deadline) {
			log.Printf("ack %d %s: still failing after %s (%v), giving up", n.DispatchID, state, limit, err)
			return false
		}
		log.Printf("ack %d %s: %v", n.DispatchID, state, err)
		time.Sleep(retryDelay(err, &retry))
	}
}

// 弹窗与浏览器启动做成可替换的变量，presentNotice 的完成处理分支才能在没有 Windows 的环境里测试。
var (
	showNoticeUI = showNotice
	openBrowser  = openChrome
)

func presentNotice(a *Agent, state *NoticeState, n *Notice) {
	shown := make(chan struct{})
	var latest *Notice
	// 度量和绘制用同一份已规范换行的文字（服务端新数据已规范；旧库里的历史文案、手工写入的数据在这里兜底）
	err := showNoticeUI(normalizeBreaks(n.Message), func() { go func() { ackUntilSent(a, n, "shown", ""); close(shown) }() }, func() { latest = state.Confirm() })
	if err != nil {
		log.Printf("popup: %v", err)
		state.Abort(n.DispatchID)
		return
	}
	<-shown
	ackUntilSent(a, latest, "confirmed", "")
	detail, openErr := openBrowser(latest.Server, latest.OpenPath)
	if openErr != nil {
		ackUntilSent(a, latest, "failed", fmt.Sprint(openErr))
	} else if detail != "" {
		ackUntilSent(a, latest, "failed", detail)
	} else {
		ackUntilSent(a, latest, "opened", "")
	}
	// 页面真的打开了（含「没找到 Chrome、改用默认浏览器」）就算处理完；只有启动失败才允许服务端再次下发（有次数上限）
	if next := state.Finish(latest.DispatchID, openErr == nil); next != nil {
		go presentNotice(a, state, next)
	}
}
