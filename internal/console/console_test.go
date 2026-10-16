package console

import "testing"

// TestEnableUTF8IsSafe 覆盖两种环境：连着控制台时会尝试切换代码页，
// 没有控制台（CI / 管道 / 子进程捕获输出）时必须静默返回且可重复调用。
func TestEnableUTF8IsSafe(t *testing.T) {
	EnableUTF8()
	EnableUTF8()
}
