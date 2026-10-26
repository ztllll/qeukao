package main

import "time"

type Backoff struct{ attempt uint }

func (b *Backoff) Next() time.Duration {
	n := time.Second << b.attempt
	if n >= 30*time.Second {
		return 30 * time.Second
	}
	b.attempt++
	return n
}
func (b *Backoff) Reset() { b.attempt = 0 }

// exitAlreadyRunning：worker 发现已经有另一个 worker 在跑（比如监护被单独结束后留下的孤儿）。
// 这不是崩溃，也不是用户选择退出——监护隔一会儿再试，等孤儿退出后接管。
const exitAlreadyRunning = 3

// GuardianPolicy 决定 worker 退出后是否重启、等多久。
//
// 「快速崩溃」= worker 存活不足 1 分钟就退出。连续快速崩溃：等 2s、4s、8s、16s、30s，第 6 次起每次等 60s；
// worker 稳定运行满 1 分钟后计数清零。
// （曾经按「1 分钟内崩溃 >5 次」的墙钟窗口计数——但前 5 次的等待加起来就已经 60 秒，窗口永远凑不满 6 次，60s 档不可达。）
type GuardianPolicy struct{ quick int }

func (p *GuardianPolicy) Exited(code int, ranFor time.Duration) (time.Duration, bool) {
	switch code {
	case 0:
		return 0, false
	case exitAlreadyRunning:
		return 30 * time.Second, true
	}
	if ranFor >= time.Minute {
		p.quick = 0
	}
	p.quick++
	if p.quick > 5 {
		return time.Minute, true
	}
	delay := 2 * time.Second << (p.quick - 1)
	if delay > 30*time.Second {
		delay = 30 * time.Second
	}
	return delay, true
}
