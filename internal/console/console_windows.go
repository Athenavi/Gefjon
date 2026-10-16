//go:build windows

// Package console 处理控制台相关的平台差异。
//
// Windows 控制台默认按本地代码页（简体中文环境是 GBK）解码输出，而 Go 直接
// 写 UTF-8 字节，于是中文会显示成乱码。这里在启动时把控制台切到 UTF-8
// （代码页 65001），并且**只在真正连着控制台时**切换 —— 输出被重定向到文件
// 或管道时，UTF-8 字节本来就是正确的，不需要也不应该改代码页。
//
// 只用标准库的 syscall，不引入 golang.org/x/text 之类的依赖。
package console

import (
	"syscall"
	"unsafe"
)

const utf8CodePage = 65001

var (
	kernel32               = syscall.NewLazyDLL("kernel32.dll")
	procGetConsoleMode     = kernel32.NewProc("GetConsoleMode")
	procSetConsoleOutputCP = kernel32.NewProc("SetConsoleOutputCP")
	procSetConsoleCP       = kernel32.NewProc("SetConsoleCP")
)

// EnableUTF8 尽力把当前控制台切到 UTF-8；任何失败都静默忽略，不影响主流程。
func EnableUTF8() {
	var mode uint32
	if ready, _, _ := procGetConsoleMode.Call(
		uintptr(syscall.Stdout), uintptr(unsafe.Pointer(&mode)),
	); ready == 0 {
		// 不是控制台（管道 / 重定向），无需切换
		return
	}

	_, _, _ = procSetConsoleOutputCP.Call(utf8CodePage)
	_, _, _ = procSetConsoleCP.Call(utf8CodePage)
}
