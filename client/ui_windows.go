package main

import (
	"fmt"
	"log"
	"os"
	"runtime"
	"sync"
	"sync/atomic"
	"syscall"
	"unsafe"
)

type point struct{ X, Y int32 }
type rect struct{ Left, Top, Right, Bottom int32 }
type message struct {
	Hwnd           uintptr
	Message        uint32
	WParam, LParam uintptr
	Time           uint32
	Pt             point
	Private        uint32
}
type wndClass struct {
	Size, Style                        uint32
	Proc                               uintptr
	ClassExtra, WindowExtra            int32
	Instance, Icon, Cursor, Background uintptr
	Menu, Name                         *uint16
	SmallIcon                          uintptr
}
type paintStruct struct {
	DC                 uintptr
	Erase              int32
	Paint              rect
	Restore, IncUpdate int32
	Reserved           [32]byte
}

var (
	createWindow     = user32.NewProc("CreateWindowExW")
	defWindow        = user32.NewProc("DefWindowProcW")
	destroyWindow    = user32.NewProc("DestroyWindow")
	postQuit         = user32.NewProc("PostQuitMessage")
	getMessage       = user32.NewProc("GetMessageW")
	translateMessage = user32.NewProc("TranslateMessage")
	dispatchMessage  = user32.NewProc("DispatchMessageW")
	popupClassOnce   sync.Once
	popupClassErr    error
	popupWindows     sync.Map
	popupCallback    = syscall.NewCallback(popupProc)
)

func registerClass(name string, callback uintptr) error {
	instance, _, _ := kernel32.NewProc("GetModuleHandleW").Call(0)
	cursor, _, _ := user32.NewProc("LoadCursorW").Call(0, 32512)
	wc := wndClass{Size: uint32(unsafe.Sizeof(wndClass{})), Proc: callback, Instance: instance, Cursor: cursor, Name: wide(name)}
	atom, _, err := user32.NewProc("RegisterClassExW").Call(uintptr(unsafe.Pointer(&wc)))
	if atom == 0 && err != syscall.Errno(1410) {
		return err
	}
	return nil
}
func messageLoop(confirm func()) error {
	var msg message
	for {
		result, _, err := getMessage.Call(uintptr(unsafe.Pointer(&msg)), 0, 0, 0)
		if int32(result) == -1 {
			return err
		}
		if result == 0 {
			return nil
		}
		if confirm != nil && msg.Message == 0x100 && msg.WParam == 13 {
			confirm()
			continue
		}
		translateMessage.Call(uintptr(unsafe.Pointer(&msg)))
		dispatchMessage.Call(uintptr(unsafe.Pointer(&msg)))
	}
}

type popup struct {
	confirmed                           func()
	body                                string
	width, height, scale                int32
	font, titleFont, buttonFont, button uintptr
}

func font(height int32, weight uintptr) uintptr {
	result, _, _ := gdi32.NewProc("CreateFontW").Call(uintptr(-height), 0, 0, 0, weight, 0, 0, 0, 1, 0, 0, 5, 0, uintptr(wp("Microsoft YaHei UI")))
	return result
}

// measuredFits 用与 WM_PAINT 完全相同的字体和 DrawText 标志（DT_WORDBREAK|DT_CENTER|DT_NOPREFIX）加 DT_CALCRECT 度量，
// 返回正文在 bodyW 宽度里排出来的高度/宽度是否都放得进 bodyW x bodyH。拿不到 DC/字体时退回估算。
func measuredFits(text string, px, bodyW, bodyH int32) bool {
	f := font(px, 500)
	if f == 0 {
		return textFits(text, px, bodyW, bodyH)
	}
	defer gdi32.NewProc("DeleteObject").Call(f)
	dc, _, _ := user32.NewProc("GetDC").Call(0)
	if dc == 0 {
		return textFits(text, px, bodyW, bodyH)
	}
	defer user32.NewProc("ReleaseDC").Call(0, dc)
	previous, _, _ := gdi32.NewProc("SelectObject").Call(dc, f)
	defer gdi32.NewProc("SelectObject").Call(dc, previous)
	r := rect{0, 0, bodyW, 0}
	drawText(dc, text, &r, 0x10|0x1|0x400|0x800)
	return r.Right-r.Left <= bodyW && r.Bottom-r.Top <= bodyH
}
func fill(dc uintptr, r rect, color uintptr) {
	brush, _, _ := gdi32.NewProc("CreateSolidBrush").Call(color)
	user32.NewProc("FillRect").Call(dc, uintptr(unsafe.Pointer(&r)), brush)
	gdi32.NewProc("DeleteObject").Call(brush)
}
func drawText(dc uintptr, text string, r *rect, flags uintptr) {
	user32.NewProc("DrawTextW").Call(dc, uintptr(wp(text)), ^uintptr(0), uintptr(unsafe.Pointer(r)), flags)
}
func popupProc(hwnd uintptr, msg uint32, wparam, lparam uintptr) uintptr {
	value, found := popupWindows.Load(hwnd)
	if found {
		p := value.(*popup)
		switch msg {
		case 0x10:
			return 0 // WM_CLOSE: intentionally ignore Alt+F4 and close requests.
		case 0x14:
			return 1
		case 0x111:
			if wparam&0xffff == 1 {
				p.confirmed()
				destroyWindow.Call(hwnd)
			}
			return 0
		case 0x2:
			postQuit.Call(0)
			return 0
		case 0xF:
			var ps paintStruct
			dc, _, _ := user32.NewProc("BeginPaint").Call(hwnd, uintptr(unsafe.Pointer(&ps)))
			fill(dc, rect{0, 0, p.width, p.height}, 0x00faf8f5)
			fill(dc, rect{0, 0, p.width, 94 * p.scale / 100}, 0x009c5321)
			gdi32.NewProc("SetBkMode").Call(dc, 1)
			previous, _, _ := gdi32.NewProc("SelectObject").Call(dc, p.titleFont)
			gdi32.NewProc("SetTextColor").Call(dc, 0x00ffffff)
			title := rect{30, 0, p.width - 30, 94 * p.scale / 100}
			drawText(dc, "考务通知", &title, 0x1|0x4|0x20)
			gdi32.NewProc("SelectObject").Call(dc, p.font)
			gdi32.NewProc("SetTextColor").Call(dc, 0x0035271c)
			body := rect{40 * p.scale / 100, 118 * p.scale / 100, p.width - 40*p.scale/100, p.height - 130*p.scale/100}
			measured := body
			drawText(dc, p.body, &measured, 0x10|0x1|0x400|0x800)
			if measured.Bottom-measured.Top < body.Bottom-body.Top {
				body.Top += (body.Bottom - body.Top - (measured.Bottom - measured.Top)) / 2
			}
			drawText(dc, p.body, &body, 0x10|0x1|0x800)
			gdi32.NewProc("SelectObject").Call(dc, previous)
			user32.NewProc("EndPaint").Call(hwnd, uintptr(unsafe.Pointer(&ps)))
			return 0
		}
	}
	result, _, _ := defWindow.Call(hwnd, uintptr(msg), wparam, lparam)
	return result
}
func forceForeground(hwnd uintptr) {
	foreground, _, _ := user32.NewProc("GetForegroundWindow").Call()
	targetThread, _, _ := user32.NewProc("GetWindowThreadProcessId").Call(foreground, 0)
	ownThread, _, _ := kernel32.NewProc("GetCurrentThreadId").Call()
	if targetThread != 0 && targetThread != ownThread {
		user32.NewProc("AttachThreadInput").Call(ownThread, targetThread, 1)
		defer user32.NewProc("AttachThreadInput").Call(ownThread, targetThread, 0)
	}
	user32.NewProc("BringWindowToTop").Call(hwnd)
	user32.NewProc("SetForegroundWindow").Call(hwnd)
	user32.NewProc("SetActiveWindow").Call(hwnd)
}
func showNotice(body string, shown, confirmed func()) error {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	user32.NewProc("SetProcessDPIAware").Call()
	popupClassOnce.Do(func() { popupClassErr = registerClass("QeukaoNotice", popupCallback) })
	if popupClassErr != nil {
		return popupClassErr
	}
	screenW, _, _ := user32.NewProc("GetSystemMetrics").Call(0)
	screenH, _, _ := user32.NewProc("GetSystemMetrics").Call(1)
	scale := int32(100)
	if proc := user32.NewProc("GetDpiForSystem"); proc.Find() == nil {
		dpi, _, _ := proc.Call()
		if dpi >= 96 {
			scale = int32(dpi) * 100 / 96
		}
	}
	width := int32(screenW) * 60 / 100
	if width < 720 {
		width = 720
	}
	if width > 1100 {
		width = 1100
	}
	height := width * 56 / 100
	if height < 420 {
		height = 420
	}
	if height > 620 {
		height = 620
	}
	// ponytail: physical 1100x620 contract ceiling caps DPI scaling; larger layouts need a revised size contract.
	if max := width * 100 / 720; scale > max {
		scale = max
	}
	if max := height * 100 / 420; scale > max {
		scale = max
	}
	// 文案长短不一（管理员自定义，最长 200 字）：短文案保持大字，长文案缩字号、必要时把窗口加高到契约上限，不裁字。
	// 是否放得下用真实 DrawText 度量，不用估算——估算在英文按词折行、CR/VT 换行、字体行高上都和实际排版对不上。
	body, height, bodyPixels, fits := layoutPopup(body, width, height, int32(screenH), scale, measuredFits)
	log.Printf("popup: layout %dx%d font=%dpx measured-fits=%v", width, height, bodyPixels, fits)
	if !fits {
		// 启发式折行点和逐字折行降级之后真实度量仍放不下（理论上只剩极端的宽字符叠加）：
		// 照样弹出（不能为了排版把考务流程卡死），尾部可能被裁，日志里能查到。
		log.Printf("popup: WARNING text does not fully fit even at the minimum font; it will be clipped")
	}
	p := &popup{body: body, width: width, height: height, scale: scale, confirmed: confirmed}
	p.font = font(bodyPixels, 500)
	p.titleFont = font(32*scale/100, 700)
	p.buttonFont = font(30*scale/100, 600)
	defer func() {
		for _, f := range []uintptr{p.font, p.titleFont, p.buttonFont} {
			gdi32.NewProc("DeleteObject").Call(f)
		}
	}()
	hwnd, _, err := createWindow.Call(0x8|0x80, uintptr(wp("QeukaoNotice")), uintptr(wp("考务通知")), 0x80000000, uintptr((int32(screenW)-width)/2), uintptr((int32(screenH)-height)/2), uintptr(width), uintptr(height), 0, 0, 0, 0)
	if hwnd == 0 {
		return fmt.Errorf("create popup: %w", err)
	}
	popupWindows.Store(hwnd, p)
	defer popupWindows.Delete(hwnd)
	bw, bh := int32(240)*scale/100, int32(76)*scale/100
	p.button, _, _ = createWindow.Call(0, uintptr(wp("BUTTON")), uintptr(wp("确定")), 0x50010001, uintptr((width-bw)/2), uintptr(height-bh-24*scale/100), uintptr(bw), uintptr(bh), hwnd, 1, 0, 0)
	user32.NewProc("SendMessageW").Call(p.button, 0x30, p.buttonFont, 1)
	user32.NewProc("ShowWindow").Call(hwnd, 5)
	user32.NewProc("UpdateWindow").Call(hwnd)
	forceForeground(hwnd)
	user32.NewProc("SetFocus").Call(p.button)
	log.Printf("popup: shown %dx%d dispatch message", width, height)
	shown()
	return messageLoop(func() { confirmed(); destroyWindow.Call(hwnd) })
}

type notifyIcon struct {
	Size                uint32
	Window              uintptr
	ID, Flags, Callback uint32
	Icon                uintptr
	Tip                 [128]uint16
	State, StateMask    uint32
	Info                [256]uint16
	Timeout             uint32
	InfoTitle           [64]uint16
	InfoFlags           uint32
	GUID                [16]byte
	BalloonIcon         uintptr
}

var trayConnected atomic.Bool
var trayWindow atomic.Uintptr
var taskbarCreated uint32
var trayData notifyIcon

func trayStatus() string {
	if trayConnected.Load() {
		return "缺考上报客户端 - 已连接"
	}
	return "缺考上报客户端 - 连接中"
}
func setTrayConnected(connected bool) {
	trayConnected.Store(connected)
	if hwnd := trayWindow.Load(); hwnd != 0 {
		user32.NewProc("PostMessageW").Call(hwnd, 0x8022, 0, 0)
	}
}
func notifyTray(operation uintptr) {
	for i := range trayData.Tip {
		trayData.Tip[i] = 0
	}
	copy(trayData.Tip[:], syscall.StringToUTF16(trayStatus()))
	ok, _, err := shell32.NewProc("Shell_NotifyIconW").Call(operation, uintptr(unsafe.Pointer(&trayData)))
	if operation == 0 {
		if ok != 0 {
			log.Print("tray: icon added ok")
		} else {
			log.Printf("tray: icon added err=%d", err)
		}
	}
}
func trayProc(hwnd uintptr, msg uint32, wparam, lparam uintptr) uintptr {
	if msg == taskbarCreated && taskbarCreated != 0 {
		notifyTray(0)
		return 0
	}
	switch msg {
	case 0x8022:
		notifyTray(1)
		return 0
	case 0x8021:
		if uint32(lparam) == 0x205 || uint32(lparam) == 0x7b {
			menu, _, _ := user32.NewProc("CreatePopupMenu").Call()
			defer user32.NewProc("DestroyMenu").Call(menu)
			user32.NewProc("AppendMenuW").Call(menu, 0x2, 0, uintptr(wp(trayStatus())))
			user32.NewProc("AppendMenuW").Call(menu, 0, 1, uintptr(wp("退出")))
			var pt point
			user32.NewProc("GetCursorPos").Call(uintptr(unsafe.Pointer(&pt)))
			user32.NewProc("SetForegroundWindow").Call(hwnd)
			selected, _, _ := user32.NewProc("TrackPopupMenu").Call(menu, 0x100|0x2, uintptr(pt.X), uintptr(pt.Y), 0, hwnd, 0)
			user32.NewProc("PostMessageW").Call(hwnd, 0, 0, 0)
			if selected == 1 {
				notifyTray(2)
				log.Print("tray: user exit")
				os.Exit(0)
			}
		}
		return 0
	case 0x10:
		return 0
	}
	result, _, _ := defWindow.Call(hwnd, uintptr(msg), wparam, lparam)
	return result
}
func runTray() {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	user32.NewProc("SetProcessDPIAware").Call()
	callback := syscall.NewCallback(trayProc)
	if err := registerClass("QeukaoTray", callback); err != nil {
		log.Printf("tray class: %v", err)
		os.Exit(1)
	}
	hwnd, _, err := createWindow.Call(0, uintptr(wp("QeukaoTray")), uintptr(wp("QeukaoTray")), 0, 0, 0, 0, 0, 0, 0, 0, 0)
	if hwnd == 0 {
		log.Printf("tray window: %v", err)
		os.Exit(1)
	}
	trayWindow.Store(hwnd)
	registered, _, _ := user32.NewProc("RegisterWindowMessageW").Call(uintptr(wp("TaskbarCreated")))
	taskbarCreated = uint32(registered)
	icon, _, _ := user32.NewProc("LoadIconW").Call(0, 32512)
	trayData = notifyIcon{Size: uint32(unsafe.Sizeof(notifyIcon{})), Window: hwnd, ID: 1, Flags: 1 | 2 | 4, Callback: 0x8021, Icon: icon}
	notifyTray(0)
	defer notifyTray(2)
	if err := messageLoop(nil); err != nil {
		log.Printf("tray loop: %v", err)
		os.Exit(1)
	}
}
