package main

import (
	"errors"
	"fmt"
	"log"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"unsafe"
)

var (
	user32   = syscall.NewLazyDLL("user32.dll")
	gdi32    = syscall.NewLazyDLL("gdi32.dll")
	kernel32 = syscall.NewLazyDLL("kernel32.dll")
	shell32  = syscall.NewLazyDLL("shell32.dll")
	advapi32 = syscall.NewLazyDLL("advapi32.dll")
)

func wide(s string) *uint16 {
	p, _ := syscall.UTF16PtrFromString(strings.ReplaceAll(s, "\x00", "")) // 含 NUL 会返回 nil 指针，传给 Win32 就崩
	return p
}
func wp(s string) unsafe.Pointer { return unsafe.Pointer(wide(s)) }

// hideProcess 只设 CREATE_NO_WINDOW。千万不要设 HideWindow：它会写入 STARTF_USESHOWWINDOW+SW_HIDE，
// Windows 规定子进程第一次调用 ShowWindow 时 nCmdShow 被这个值覆盖——worker 的弹窗就会隐藏，
// 老师看不到，而回执却照样报「已显示」。
func hideProcess(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x08000000}
}
func singleInstance(role string) (func(), bool) {
	handle, _, err := kernel32.NewProc("CreateMutexW").Call(0, 0, uintptr(wp("Local\\QeukaoClient-"+role)))
	if handle == 0 {
		log.Printf("mutex: %v", err)
		return func() {}, false
	}
	if err == syscall.Errno(183) {
		syscall.CloseHandle(syscall.Handle(handle))
		return func() {}, false
	}
	return func() { syscall.CloseHandle(syscall.Handle(handle)) }, true
}
func sameFile(a, b string) bool {
	ia, e1 := os.Stat(a)
	ib, e2 := os.Stat(b)
	if e1 == nil && e2 == nil {
		return os.SameFile(ia, ib) // 按文件标识比较：8.3 短名、subst 盘符、junction 写法不同也认得出是同一个文件
	}
	return strings.EqualFold(filepath.Clean(a), filepath.Clean(b))
}

// copyOver 把 src 复制到 dest。dest 正被旧客户端运行时 CopyFileW 会失败；Windows 允许给运行中的 exe 改名，
// 所以先让位再复制：下次登录/重启起来的就是新配置（正在运行的旧进程要等它退出或重启才会换掉）。
func copyOver(src, dest string) error {
	ok, _, copyErr := kernel32.NewProc("CopyFileW").Call(uintptr(wp(src)), uintptr(wp(dest)), 0)
	if ok != 0 {
		return nil
	}
	if _, err := os.Stat(dest); err != nil {
		return fmt.Errorf("copy client: %w", copyErr)
	}
	old := dest + ".old"
	os.Remove(old)
	if err := os.Rename(dest, old); err == nil {
		if ok, _, e := kernel32.NewProc("CopyFileW").Call(uintptr(wp(src)), uintptr(wp(dest)), 0); ok != 0 {
			log.Printf("install: replaced the running installed copy; the new configuration applies after it restarts")
			return nil
		} else {
			os.Rename(old, dest) // 回滚，别把安装路径弄成空的
			copyErr = e
		}
	}
	log.Printf("install: target busy, kept installed executable: %v", copyErr)
	return nil
}
func ensureRunKey(dest string) error {
	var key syscall.Handle
	status, _, _ := advapi32.NewProc("RegCreateKeyExW").Call(uintptr(syscall.HKEY_CURRENT_USER), uintptr(wp("Software\\Microsoft\\Windows\\CurrentVersion\\Run")), 0, 0, 0, 0x0002, 0, uintptr(unsafe.Pointer(&key)), 0)
	if status != 0 {
		return syscall.Errno(status)
	}
	value := syscall.StringToUTF16("\"" + dest + "\"")
	status, _, _ = advapi32.NewProc("RegSetValueExW").Call(uintptr(key), uintptr(wp("QeukaoClient")), 0, 1, uintptr(unsafe.Pointer(&value[0])), uintptr(len(value)*2))
	syscall.RegCloseKey(key)
	if status != 0 {
		return syscall.Errno(status)
	}
	return nil
}

// installSelf 返回 done=true 表示已经把安装路径的副本拉起来了，当前进程应该退出。
// err 不为 nil 时调用方应就地继续运行（安装失败不能让客户端整个不工作）。
func installSelf() (bool, error) {
	if os.Getenv("QEUKAO_CLIENT_NO_INSTALL") == "1" {
		return false, nil
	}
	exe, err := os.Executable()
	if err != nil {
		return false, err
	}
	local := os.Getenv("LOCALAPPDATA")
	if local == "" {
		return false, errors.New("LOCALAPPDATA is not set")
	}
	dest := filepath.Join(local, "QeukaoClient", "qeukao-client.exe")
	if err := os.MkdirAll(filepath.Dir(dest), 0700); err != nil {
		return false, err
	}
	installed := sameFile(exe, dest)
	if installed {
		os.Remove(dest + ".old") // 上次更新让位留下的旧文件，能删就删
	} else if err := copyOver(exe, dest); err != nil {
		return false, err
	}
	if err := ensureRunKey(dest); err != nil {
		return false, err
	}
	if installed {
		return false, nil
	}
	// --installed：被拉起的副本不要再走一遍安装。否则只要两边的路径写法对不上，就会无限自我拉起。
	cmd := exec.Command(dest, append([]string{"--installed"}, os.Args[1:]...)...)
	hideProcess(cmd)
	if err := cmd.Start(); err != nil {
		return false, err
	}
	cmd.Process.Release()
	return true, nil
}
func registryString(root syscall.Handle, path string) (string, error) {
	var key syscall.Handle
	err := syscall.RegOpenKeyEx(root, wide(path), 0, syscall.KEY_READ, &key)
	if err != nil {
		return "", err
	}
	defer syscall.RegCloseKey(key)
	var kind, n uint32
	if err := syscall.RegQueryValueEx(key, nil, nil, &kind, nil, &n); err != nil {
		return "", err
	}
	if (kind != syscall.REG_SZ && kind != syscall.REG_EXPAND_SZ) || n < 2 || n > 32768 {
		return "", errors.New("invalid registry path")
	}
	buf := make([]uint16, (n+1)/2)
	if err := syscall.RegQueryValueEx(key, nil, nil, &kind, (*byte)(unsafe.Pointer(&buf[0])), &n); err != nil {
		return "", err
	}
	value := syscall.UTF16ToString(buf)
	if kind == syscall.REG_EXPAND_SZ {
		expanded := make([]uint16, 32768)
		count, _, _ := kernel32.NewProc("ExpandEnvironmentStringsW").Call(uintptr(wp(value)), uintptr(unsafe.Pointer(&expanded[0])), uintptr(len(expanded)))
		if count > 0 && count <= uintptr(len(expanded)) {
			value = syscall.UTF16ToString(expanded)
		}
	}
	return strings.Trim(value, "\""), nil
}
func findChrome() string {
	candidates := []string{}
	if path := os.Getenv("QEUKAO_CHROME_PATH"); path != "" {
		candidates = append(candidates, path)
	}
	for _, root := range []syscall.Handle{syscall.HKEY_LOCAL_MACHINE, syscall.HKEY_CURRENT_USER} {
		if path, e := registryString(root, "Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\chrome.exe"); e == nil {
			candidates = append(candidates, path)
		}
	}
	for _, base := range []string{"ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"} {
		if dir := os.Getenv(base); dir != "" {
			candidates = append(candidates, filepath.Join(dir, "Google", "Chrome", "Application", "chrome.exe"))
		}
	}
	for _, path := range candidates {
		if info, e := os.Stat(path); e == nil && !info.IsDir() {
			return path
		}
	}
	return ""
}
func openChrome(server, path string) (string, error) {
	parsed, err := url.Parse(path)
	if err != nil || !strings.HasPrefix(path, "/") || strings.HasPrefix(path, "//") || parsed.IsAbs() || parsed.Host != "" || strings.ContainsAny(path, "\\\x00\r\n") {
		return "", errors.New("invalid notice openPath")
	}
	target := strings.TrimRight(server, "/") + path
	if chrome := findChrome(); chrome != "" {
		cmd := exec.Command(chrome, "--new-window", target) // Chrome 是要给人看的窗口：不套 hideProcess
		if err := cmd.Start(); err != nil {
			return "", err
		}
		cmd.Process.Release()
		return "", nil
	}
	result, _, err := shell32.NewProc("ShellExecuteW").Call(0, uintptr(wp("open")), uintptr(wp(target)), 0, 0, 1)
	if result <= 32 {
		return "", fmt.Errorf("default browser: result=%d %v", result, err)
	}
	return "chrome-not-found,used-default-browser", nil
}
