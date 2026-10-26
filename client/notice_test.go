package main

import "testing"

func TestNoticeReplacesDispatchWithoutStacking(t *testing.T) {
	var notices NoticeState
	if !notices.Receive(&Notice{DispatchID: 1, Message: "first"}) {
		t.Fatal("first notice did not open")
	}
	// 服务端始终返回「最新触发」的那条：后收到的就是最新，弹窗不叠加
	if notices.Receive(&Notice{DispatchID: 3, Message: "newer"}) || notices.Receive(&Notice{DispatchID: 2, Message: "latest-fired"}) {
		t.Fatal("notice stacked popup")
	}
	confirmed := notices.Confirm()
	if confirmed.DispatchID != 2 {
		t.Fatalf("confirmed %d, want the latest the server returned (2)", confirmed.DispatchID)
	}
	if notices.Receive(&Notice{DispatchID: 4}) {
		t.Fatal("new notice stacked while confirmation is in flight")
	}
	if next := notices.Finish(confirmed.DispatchID, true); next == nil || next.DispatchID != 4 {
		t.Fatal("notice arriving after click was lost")
	}
	notices.Confirm()
	notices.Finish(4, true)
	if notices.Receive(&Notice{DispatchID: 2}) || notices.Receive(&Notice{DispatchID: 4}) {
		t.Fatal("already handled notice reopened")
	}
	if !notices.Receive(&Notice{DispatchID: 5}) {
		t.Fatal("next notice did not open")
	}
}
