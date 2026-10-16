// Package detect 探测项目技术栈，据此推荐迁移后端。
//
// 目的：`gefjon init` 不该让用户在四个后端之间盲选 —— 项目里已有的
// go.mod / pyproject.toml / pom.xml 就是最好的线索。
package detect

import (
	"os"
	"path/filepath"
)

// Kind 是后端种类。
type Kind string

const (
	// KindAtlas 用 atlas 执行（单个 Go 二进制，零环境依赖）。
	KindAtlas Kind = "atlas"
	// KindAlembic 用 alembic 执行（Python 生态）。
	KindAlembic Kind = "alembic"
	// KindFlyway 用 flyway 执行（JVM 生态）。
	KindFlyway Kind = "flyway"
	// KindPlainSQL 只产出纯 SQL（不绑定任何执行工具）。
	KindPlainSQL Kind = "plain-sql"
)

// Recommendation 是一条后端推荐。
type Recommendation struct {
	Kind Kind
	// Dir 是该后端的默认产物目录。
	Dir string
	// Reason 是推荐理由（直接展示给用户）。
	Reason string
	// Evidence 是命中的文件名。
	Evidence []string
}

type rule struct {
	kind   Kind
	dir    string
	files  []string
	reason string
}

// 按顺序匹配；一个项目可能命中多条（多语言仓库）。
var rules = []rule{
	{
		kind:   KindAtlas,
		dir:    "db/migrations",
		files:  []string{"go.mod"},
		reason: "检测到 go.mod：atlas 是单个 Go 二进制，最能保持“零环境依赖”",
	},
	{
		kind:   KindAlembic,
		dir:    "migrations",
		files:  []string{"pyproject.toml", "requirements.txt", "setup.py", "setup.cfg", "Pipfile"},
		reason: "检测到 Python 项目文件：alembic 与现有 Python 生态一致",
	},
	{
		kind:   KindFlyway,
		dir:    "src/main/resources/db/migration",
		files:  []string{"pom.xml", "build.gradle", "build.gradle.kts", "build.sbt"},
		reason: "检测到 JVM 项目文件：flyway 是 Java 生态的标准选择",
	},
	{
		kind:   KindPlainSQL,
		dir:    "migrations",
		files:  []string{"package.json"},
		reason: "检测到 package.json：Node 生态暂无统一迁移工具，先产出纯 SQL",
	},
}

// defaultDirs 是各后端的默认产物目录（用于显式指定 kind 的场景）。
var defaultDirs = map[Kind]string{
	KindAtlas:    "db/migrations",
	KindAlembic:  "migrations",
	KindFlyway:   "src/main/resources/db/migration",
	KindPlainSQL: "migrations",
}

// Detect 扫描 root，按规则顺序返回命中的推荐；一条都没命中时给出默认项。
func Detect(root string) []Recommendation {
	recommendations := make([]Recommendation, 0, len(rules))

	for _, candidate := range rules {
		var evidence []string
		for _, name := range candidate.files {
			if _, err := os.Stat(filepath.Join(root, name)); err == nil {
				evidence = append(evidence, name)
			}
		}
		if len(evidence) == 0 {
			continue
		}
		recommendations = append(recommendations, Recommendation{
			Kind:     candidate.kind,
			Dir:      candidate.dir,
			Reason:   candidate.reason,
			Evidence: evidence,
		})
	}

	if len(recommendations) == 0 {
		recommendations = append(recommendations, Recommendation{
			Kind:   KindPlainSQL,
			Dir:    "migrations",
			Reason: "未探测到已知技术栈；先产出纯 SQL 迁移（之后可随时改用其它后端）",
		})
	}
	return recommendations
}

// DefaultDir 返回某个后端的默认产物目录。
func DefaultDir(kind Kind) string {
	if dir, ok := defaultDirs[kind]; ok {
		return dir
	}
	return "migrations"
}

// IsKnown 判断 kind 是否是支持的后端。
func IsKnown(kind Kind) bool {
	_, ok := defaultDirs[kind]
	return ok
}

// KnownKinds 返回全部支持的后端（用于错误提示）。
func KnownKinds() []Kind {
	return []Kind{KindAtlas, KindAlembic, KindFlyway, KindPlainSQL}
}
