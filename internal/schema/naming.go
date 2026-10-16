package schema

import (
	"regexp"
	"strings"
)

var (
	firstBoundaryPattern  = regexp.MustCompile(`(.)([A-Z][a-z]+)`)
	secondBoundaryPattern = regexp.MustCompile(`([a-z0-9])([A-Z])`)
	identifierPattern     = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*$`)
)

// ReservedNames 是 SQLAlchemy 声明式基类上已占用的属性名。
//
// 冲突时字段的 Python 属性名会被改写成 extra_ 前缀，数据库列名保持不变。
var ReservedNames = map[string]struct{}{
	"metadata": {},
	"registry": {},
	"query":    {},
	"session":  {},
}

// pythonKeywords 与 Python 的 keyword.kwlist 加上 True/False/None 对齐。
//
// 生成产物是 Python 代码，因此字段名不能是 Python 关键字。
var pythonKeywords = map[string]struct{}{
	"False": {}, "None": {}, "True": {},
	"and": {}, "as": {}, "assert": {}, "async": {}, "await": {},
	"break": {}, "class": {}, "continue": {}, "def": {}, "del": {},
	"elif": {}, "else": {}, "except": {}, "finally": {}, "for": {},
	"from": {}, "global": {}, "if": {}, "import": {}, "in": {},
	"is": {}, "lambda": {}, "nonlocal": {}, "not": {}, "or": {},
	"pass": {}, "raise": {}, "return": {}, "try": {}, "while": {},
	"with": {}, "yield": {},
}

// IsValidIdentifier 判断名字能否安全地作为 Python 标识符写进生成代码。
func IsValidIdentifier(name string) bool {
	if !identifierPattern.MatchString(name) {
		return false
	}
	_, isKeyword := pythonKeywords[name]
	return !isKeyword
}

// ToSnakeCase 把驼峰转成下划线：MediaAsset -> media_asset。
func ToSnakeCase(name string) string {
	first := firstBoundaryPattern.ReplaceAllString(name, "${1}_${2}")
	snake := secondBoundaryPattern.ReplaceAllString(first, "${1}_${2}")
	return strings.ToLower(snake)
}

// ToModuleName 返回模型名对应的模块名（不含扩展名）。
func ToModuleName(modelName string) string {
	return ToSnakeCase(modelName)
}

// ToTableName 返回表名。
//
// 显式配置优先；否则用 snake_case 加简单复数（User -> users），与 v0.1 一致。
func ToTableName(modelName, explicit string) string {
	if explicit != "" {
		return explicit
	}
	base := ToSnakeCase(modelName)
	if !strings.HasSuffix(base, "s") {
		base += "s"
	}
	return base
}
