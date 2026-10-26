package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"sync"
	"time"
)

type Notice struct {
	DispatchID int    `json:"dispatchId"`
	Title      string `json:"title"`
	Message    string `json:"message"`
	OpenPath   string `json:"openPath"`
	Server     string `json:"-"`
}
type APIError struct {
	Status  int
	Code    string
	Message string
}

func (e *APIError) Error() string {
	return fmt.Sprintf("agent HTTP %d %s: %s", e.Status, e.Code, e.Message)
}

type Agent struct {
	cfg     Config
	id      string
	http    *http.Client
	mu      sync.Mutex
	current int
}

func NewAgent(cfg Config, id string) *Agent {
	// 教室机的 servers 里会有服务端所有网卡的地址（含虚拟网卡），不可达地址的 SYN 会被直接丢弃：
	// 拨号 3 秒就放弃，别让每个坏地址白等 35 秒。内网地址不走系统代理。
	transport := &http.Transport{
		Proxy:               nil,
		DialContext:         (&net.Dialer{Timeout: 3 * time.Second, KeepAlive: 30 * time.Second}).DialContext,
		TLSHandshakeTimeout: 5 * time.Second,
		MaxIdleConns:        2,
		IdleConnTimeout:     60 * time.Second,
	}
	return &Agent{cfg: cfg, id: id, http: &http.Client{Transport: transport, Timeout: 35 * time.Second, CheckRedirect: func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse }}}
}
func (a *Agent) server() string { a.mu.Lock(); defer a.mu.Unlock(); return a.cfg.Servers[a.current] }
func (a *Agent) rotate() {
	a.mu.Lock()
	a.current = (a.current + 1) % len(a.cfg.Servers)
	a.mu.Unlock()
}
func (a *Agent) request(ctx context.Context, server, method, path string, body interface{}, out interface{}) error {
	var reader io.Reader
	if body != nil {
		data, err := json.Marshal(body)
		if err != nil {
			return err
		}
		reader = bytes.NewReader(data)
	}
	req, err := http.NewRequestWithContext(ctx, method, server+path, reader)
	if err != nil {
		return err
	}
	req.Header.Set("X-Qk-Key", a.cfg.EnrollKey)
	req.Header.Set("Content-Type", "application/json")
	resp, err := a.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	var envelope struct {
		Success bool            `json:"success"`
		Data    json.RawMessage `json:"data"`
		Error   struct {
			Code    string
			Message string
		} `json:"error"`
	}
	if err := json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&envelope); err != nil {
		return err
	}
	if resp.StatusCode != 200 || !envelope.Success {
		return &APIError{resp.StatusCode, envelope.Error.Code, envelope.Error.Message}
	}
	if out != nil {
		return json.Unmarshal(envelope.Data, out)
	}
	return nil
}
func (a *Agent) Connect(ctx context.Context) error {
	hostname, _ := os.Hostname()
	ips := []string{}
	if addrs, e := net.InterfaceAddrs(); e == nil {
		for _, addr := range addrs {
			if ip, _, e := net.ParseCIDR(addr.String()); e == nil && !ip.IsLoopback() {
				ips = append(ips, ip.String())
			}
		}
	}
	body := map[string]interface{}{"clientId": a.id, "hostname": hostname, "version": "1.0.0", "localIps": ips}
	var last error
	for range a.cfg.Servers {
		last = a.request(ctx, a.server(), "POST", "/api/agent/hello", body, nil)
		if last == nil {
			return nil
		}
		if api, ok := last.(*APIError); ok && (api.Status == 401 || api.Status == 403) {
			return last
		}
		a.rotate()
	}
	return last
}
func (a *Agent) Poll(ctx context.Context) (*Notice, error) {
	server := a.server()
	var data struct {
		Notice *Notice `json:"notice"`
	}
	err := a.request(ctx, server, "GET", "/api/agent/poll?clientId="+url.QueryEscape(a.id)+"&wait=25", nil, &data)
	if err != nil {
		return nil, err
	}
	if data.Notice != nil {
		data.Notice.Server = server
	}
	return data.Notice, nil
}
func (a *Agent) Ack(ctx context.Context, n *Notice, state, detail string) error {
	body := map[string]interface{}{"clientId": a.id, "dispatchId": n.DispatchID, "state": state}
	if detail != "" {
		body["detail"] = detail
	}
	// 回执发往「当前」服务端，而不是通知当初来自的地址：那个地址可能已经失效、轮询早已换到别的地址。
	return a.request(ctx, a.server(), "POST", "/api/agent/ack", body, nil)
}
