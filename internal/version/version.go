// Package version 暴露构建期注入的版本信息。
//
// 这些变量由 -ldflags "-X ..." 在构建时注入（见 Makefile），
// 因此源码里不需要写死版本号。
package version

var (
	// Version 是发布版本，例如 v0.2.0。
	Version = "0.2.0-dev"
	// Commit 是构建所用的 git commit 短哈希。
	Commit = "unknown"
	// BuildDate 是构建时间（UTC，RFC3339）。
	BuildDate = "unknown"
)

// Info 是一次构建的版本信息快照。
type Info struct {
	Version   string
	Commit    string
	BuildDate string
}

// Get 返回当前二进制的版本信息。
func Get() Info {
	return Info{Version: Version, Commit: Commit, BuildDate: BuildDate}
}
