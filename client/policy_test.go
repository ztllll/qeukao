package main

import (
	"testing"
	"time"
)

func TestBackoff(t *testing.T) {
	var retry Backoff
	for _, want := range []time.Duration{1, 2, 4, 8, 16, 30, 30} {
		if got := retry.Next(); got != want*time.Second {
			t.Fatalf("retry=%v want=%vs", got, want)
		}
	}
	retry.Reset()
	if retry.Next() != time.Second {
		t.Fatal("retry did not reset")
	}
}

// 契约 §7：快速崩溃 2/4/8/16/30s，第 6 次起 60s；用「真实等待」累加，证明 60s 档可达（旧实现按墙钟窗口，永远到不了）。
func TestGuardianReachesTheSixtySecondTier(t *testing.T) {
	var g GuardianPolicy
	for i, want := range []time.Duration{2, 4, 8, 16, 30, 60, 60} {
		delay, restart := g.Exited(1, time.Second) // worker 活了 1 秒就崩
		if !restart || delay != want*time.Second {
			t.Fatalf("crash #%d delay=%v restart=%v want=%vs", i+1, delay, restart, want)
		}
	}
}

func TestGuardianResetsAfterAStableRunAndNeverRestartsOnUserExit(t *testing.T) {
	var g GuardianPolicy
	for i := 0; i < 8; i++ {
		g.Exited(1, time.Second)
	}
	if delay, _ := g.Exited(1, 2*time.Minute); delay != 2*time.Second {
		t.Fatalf("a stable run must reset the counter, got %v", delay)
	}
	if _, restart := g.Exited(0, time.Hour); restart {
		t.Fatal("normal user exit restarted worker")
	}
}

// 孤儿 worker 还在时，新 worker 抢不到互斥体：这不是「用户退出」，监护不能因此退出。
func TestGuardianKeepsGoingWhenAnotherWorkerIsAlreadyRunning(t *testing.T) {
	var g GuardianPolicy
	delay, restart := g.Exited(exitAlreadyRunning, time.Second)
	if !restart || delay <= 0 {
		t.Fatalf("already-running worker must be retried later, got restart=%v delay=%v", restart, delay)
	}
}

// 监护进程自己不能死：run() 里 panic 只当作 worker 异常退出，要继续重启。
func TestSuperviseOnceSurvivesAPanic(t *testing.T) {
	var g GuardianPolicy
	delay, restart := superviseOnce(func() int { panic("boom") }, &g)
	if !restart || delay <= 0 {
		t.Fatalf("a panic must lead to a restart, got restart=%v delay=%v", restart, delay)
	}
	if _, restart := superviseOnce(func() int { return 0 }, &g); restart {
		t.Fatal("exit code 0 must stop the guard")
	}
}
