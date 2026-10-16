// Package assets 存放随二进制分发的内嵌资源。
//
// 资源用 go:embed 编进单一二进制，运行时**不需要任何外部文件**。
// 这是对 v0.1 那类故障的根治：v0.1 从包数据读取模板与脚手架，
// 一旦 package-data 漏配（例如把 *.ini 写成实际文件名 *.template），
// 源码目录里测试全绿、安装后才报"内置脚手架缺少文件"。
package assets

import _ "embed"

// SampleModels 是 `gefjon init` 写出的示例 models.yaml。
//
//go:embed sample-models.yaml
var SampleModels string
