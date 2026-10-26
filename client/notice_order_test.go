package main

import "testing"

// 先建的定时通知(id 小)在后建的立即通知(id 大)被处理之后才触发：服务端按触发先后返回它，客户端必须弹窗。
func TestOlderScheduledNoticeStillShowsAfterNewerWasHandled(t *testing.T) {
	var s NoticeState
	if !s.Receive(&Notice{DispatchID: 2, Message: "立即"}) {
		t.Fatal("first notice did not open")
	}
	s.Confirm()
	s.Finish(2, true)
	if !s.Receive(&Notice{DispatchID: 1, Message: "定时"}) {
		t.Fatal("older id fired later was dropped")
	}
}

// 启动失败（回执 failed）时服务端会再次下发同一条，客户端允许重弹；页面已打开的则不再弹。
func TestFailedLaunchIsOfferedAgainButOpenedIsNot(t *testing.T) {
	var s NoticeState
	s.Receive(&Notice{DispatchID: 7})
	s.Confirm()
	s.Finish(7, false)
	if !s.Receive(&Notice{DispatchID: 7}) {
		t.Fatal("failed launch must be retried")
	}
	s.Confirm()
	s.Finish(7, true)
	if s.Receive(&Notice{DispatchID: 7}) {
		t.Fatal("opened notice must not pop up again")
	}
}

// 持续启动失败（Chrome 被策略禁止执行）：重弹有上限，之后安静下来，老师不会被同一个不可关闭的窗口无限纠缠。
func TestPersistentLaunchFailureStopsRePopping(t *testing.T) {
	var s NoticeState
	pops := 0
	for i := 0; i < 20; i++ {
		if !s.Receive(&Notice{DispatchID: 9}) {
			break
		}
		pops++
		s.Confirm()
		s.Finish(9, false)
	}
	if pops != maxLaunchAttempts {
		t.Fatalf("popped %d times, want exactly %d", pops, maxLaunchAttempts)
	}
	if !s.Receive(&Notice{DispatchID: 10}) {
		t.Fatal("a new dispatch must still pop up after an old one gave up")
	}
}

// 弹窗创建失败不能让状态卡在 active，否则之后所有通知都再也弹不出来；但持续失败也不能无限重试。
func TestAbortLetsThePollRetryButOnlyBoundedTimes(t *testing.T) {
	var s NoticeState
	tries := 0
	for i := 0; i < 20; i++ {
		if !s.Receive(&Notice{DispatchID: 3}) {
			break
		}
		tries++
		s.Abort(3)
	}
	if tries != maxLaunchAttempts {
		t.Fatalf("popup creation retried %d times, want exactly %d", tries, maxLaunchAttempts)
	}
	if !s.Receive(&Notice{DispatchID: 4}) {
		t.Fatal("a new dispatch must still be shown after an old one gave up")
	}
}
