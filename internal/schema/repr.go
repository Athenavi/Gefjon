package schema

import (
	"fmt"
	"strings"
)

// PyRepr 返回尽量与 Python 内置 repr() 一致的字面量。
//
// 为什么必须复刻：产物要与 v0.1 **逐字节一致**，而 v0.1 用 Python 的 repr()
// 转义用户输入（默认值、doc、枚举取值、列名、DOMAIN 名……）。
// 引号选择规则：
//   - 不含单引号  -> 用单引号包裹
//   - 含单引号、不含双引号 -> 用双引号包裹
//   - 两种都有    -> 用单引号包裹，内部单引号转义
func PyRepr(value string) string {
	hasSingle := strings.Contains(value, "'")
	hasDouble := strings.Contains(value, `"`)

	quote := byte('\'')
	if hasSingle && !hasDouble {
		quote = '"'
	}

	var builder strings.Builder
	builder.WriteByte(quote)
	for _, r := range value {
		switch {
		case r == '\\':
			builder.WriteString(`\\`)
		case r == '\n':
			builder.WriteString(`\n`)
		case r == '\r':
			builder.WriteString(`\r`)
		case r == '\t':
			builder.WriteString(`\t`)
		case byte(r) == quote:
			builder.WriteByte('\\')
			builder.WriteRune(r)
		case r < 0x20 || r == 0x7f:
			builder.WriteString(fmt.Sprintf(`\x%02x`, r))
		default:
			builder.WriteRune(r)
		}
	}
	builder.WriteByte(quote)
	return builder.String()
}
