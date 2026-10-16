//go:build !windows

package console

// EnableUTF8 在非 Windows 平台是空操作：终端本来就是 UTF-8。
func EnableUTF8() {}
