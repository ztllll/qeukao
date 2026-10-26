package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestAgentRoundTripAndFailover(t *testing.T) {
	var requests []string
	status := 200
	server := &httptest.Server{Config: &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Qk-Key") != "test-key" {
			t.Error("missing enrollment header")
		}
		requests = append(requests, r.Method+" "+r.URL.Path)
		w.Header().Set("Content-Type", "application/json")
		if status != 200 {
			w.WriteHeader(status)
			code := "UNAUTHORIZED"
			if status == 403 {
				code = "CLIENT_BLOCKED"
			}
			fmt.Fprintf(w, `{"success":false,"error":{"code":%q,"message":"denied"}}`, code)
			return
		}
		switch r.URL.Path {
		case "/api/agent/hello":
			var body map[string]interface{}
			json.NewDecoder(r.Body).Decode(&body)
			if body["clientId"] != "0123456789abcdef" || body["hostname"] == nil || body["version"] == nil || body["localIps"] == nil {
				t.Errorf("invalid hello: %v", body)
			}
			fmt.Fprint(w, `{"success":true,"data":{"serverTime":"2026-10-25T12:00:00+08:00","serverName":"test","pollSeconds":25,"room":{"matched":false}}}`)
		case "/api/agent/poll":
			if r.URL.Query().Get("clientId") != "0123456789abcdef" || r.URL.Query().Get("wait") != "25" {
				t.Error("invalid poll query")
			}
			fmt.Fprint(w, `{"success":true,"data":{"serverTime":"2026-10-25T12:00:00+08:00","session":{"open":true},"notice":{"dispatchId":42,"title":"Exam","message":"Please confirm","openPath":"/"}}}`)
		case "/api/agent/ack":
			var body map[string]interface{}
			json.NewDecoder(r.Body).Decode(&body)
			if body["dispatchId"] != float64(42) || body["state"] != "shown" || body["clientId"] != "0123456789abcdef" {
				t.Errorf("bad ack: %v", body)
			}
			fmt.Fprint(w, `{"success":true,"data":{"ok":true}}`)
		default:
			t.Errorf("unexpected request %s", r.URL)
		}
	})}}
	var listener net.Listener
	for port := 18000; port < 19000; port++ {
		l, e := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", port))
		if e == nil {
			listener = l
			break
		}
	}
	if listener == nil {
		t.Fatal("no independent test port available")
	}
	server.Listener = listener
	server.Start()
	defer server.Close()
	// A just-closed listener guarantees a network error without reaching another service.
	var dead net.Listener
	for port := 18999; port >= 18000; port-- {
		if candidate, e := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", port)); e == nil {
			dead = candidate
			break
		}
	}
	if dead == nil {
		t.Fatal("no independent failover test port available")
	}
	deadURL := "http://" + dead.Addr().String()
	dead.Close()
	agent := NewAgent(Config{V: 1, Servers: []string{deadURL, server.URL}, EnrollKey: "test-key"}, "0123456789abcdef")
	ctx := context.Background()
	if err := agent.Connect(ctx); err != nil {
		t.Fatal(err)
	}
	notice, err := agent.Poll(ctx)
	if err != nil || notice == nil || notice.DispatchID != 42 {
		t.Fatalf("poll: %v %v", notice, err)
	}
	if err := agent.Ack(ctx, notice, "shown", ""); err != nil {
		t.Fatal(err)
	}
	if len(requests) != 3 {
		t.Fatalf("roundtrip requests %v", requests)
	}
	for _, s := range []int{401, 403} {
		status = s
		if _, err := agent.Poll(ctx); err == nil {
			t.Fatal("accepted rejected poll")
		} else {
			var api *APIError
			if !errors.As(err, &api) || api.Status != s || (s == 403 && api.Code != "CLIENT_BLOCKED") {
				t.Fatalf("bad auth error %v", err)
			}
		}
	}
}
