package main

import (
	"log"
	"sync"
)

// maxLaunchAttempts：同一条通知连续启动浏览器失败这么多次后，客户端本进程内不再重弹（管理端仍能看到 failed 回执）。
// 否则 Chrome 被策略禁止执行时，老师每点一次确定又弹回来，没有出路。
const maxLaunchAttempts = 3

// NoticeState keeps at most one popup active while poll continues receiving dispatches.
//
// 服务端按「触发先后」返回最新一条通知，所以客户端不能用 id 大小判断新旧（先建的定时通知可能后触发）。
// 这里只记录「已经处理完」的通知 id 集合：页面确实被打开（含默认浏览器兜底）才算处理完；
// 启动失败不立即记入，服务端会因回执 failed 再次下发，从而重新弹窗——但有次数上限。
type NoticeState struct {
	mu       sync.Mutex
	current  *Notice
	active   bool
	handled  map[int]bool
	failures map[int]int
}

func (s *NoticeState) Receive(n *Notice) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.handled[n.DispatchID] {
		return false
	}
	// 同一个 poll 循环顺序收到的就是服务端当前认定的最新通知，直接取最后一条
	if s.current == nil || n.DispatchID != s.current.DispatchID {
		copy := *n
		s.current = &copy
	}
	if s.active {
		return false
	}
	s.active = true
	return true
}

func (s *NoticeState) Confirm() *Notice {
	s.mu.Lock()
	defer s.mu.Unlock()
	copy := *s.current
	return &copy
}

// Finish 结束当前弹窗。handled=true 表示这条通知处理完毕，之后不再弹；
// handled=false（启动失败）最多再弹 maxLaunchAttempts-1 次。
// 若期间服务端换了更新的通知，返回它让调用方继续弹。
func (s *NoticeState) Finish(id int, handled bool) *Notice {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !handled {
		if s.failures == nil {
			s.failures = map[int]int{}
		}
		s.failures[id]++
		if s.failures[id] >= maxLaunchAttempts {
			log.Printf("notice %d: browser launch failed %d times, not showing it again until a new dispatch", id, maxLaunchAttempts)
			handled = true
		}
	}
	if handled {
		if s.handled == nil {
			s.handled = map[int]bool{}
		}
		s.handled[id] = true
	}
	s.active = false
	if s.current != nil && s.current.DispatchID != id && !s.handled[s.current.DispatchID] {
		s.active = true
		copy := *s.current
		return &copy
	}
	return nil
}

// Abort 在弹窗创建失败时放弃当前弹窗：不立即记为已处理，下一次 poll 会重新收到并重试；
// 但和启动浏览器失败一样有次数上限，否则弹窗持续创建失败（例如没有桌面会话）会每 0.5 秒无限重试并刷日志。
func (s *NoticeState) Abort(id int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.failures == nil {
		s.failures = map[int]int{}
	}
	s.failures[id]++
	if s.failures[id] >= maxLaunchAttempts {
		log.Printf("notice %d: popup could not be created %d times, giving up until a new dispatch", id, maxLaunchAttempts)
		if s.handled == nil {
			s.handled = map[int]bool{}
		}
		s.handled[id] = true
	}
	s.active = false
	s.current = nil
}
