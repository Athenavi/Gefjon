// Package schema 定义与后端无关的 schema 中间表示（IR）。
//
// models.yaml 先被解析并校验成这里的结构，再由各 backend 编译成目标生态的产物
// （alembic 的 *.py、atlas 的 *.hcl / *.sql、Go ORM 的模型代码……）。
// IR 刻意不携带语言/框架细节 —— 那是 backend 的职责。
package schema

import (
	"fmt"

	"gopkg.in/yaml.v3"
)

// ── 保序映射 ─────────────────────────────────────────────────────────

// Entry 是保序映射中的一项。
type Entry[T any] struct {
	Key   string
	Value T
}

// Ordered 是保序映射。
//
// 必须保序：产物要与 v0.1 逐字节一致，而 v0.1 遍历的是 Python dict 的插入顺序
// （即 YAML 中的书写顺序，例如 index.ops / index.lengths 生成的 kwargs 顺序）。
// Go 的 map 无序，直接用会破坏这一约定。
type Ordered[T any] []Entry[T]

// UnmarshalYAML 实现 yaml.Unmarshaler，按出现顺序保留键值对。
func (o *Ordered[T]) UnmarshalYAML(node *yaml.Node) error {
	if node.Kind != yaml.MappingNode {
		return fmt.Errorf("期望映射，收到 %s", node.Tag)
	}

	entries := make(Ordered[T], 0, len(node.Content)/2)
	for i := 0; i+1 < len(node.Content); i += 2 {
		var key string
		if err := node.Content[i].Decode(&key); err != nil {
			return fmt.Errorf("映射的键必须是字符串：%w", err)
		}
		var value T
		if err := node.Content[i+1].Decode(&value); err != nil {
			return fmt.Errorf("%q 的值无效：%w", key, err)
		}
		entries = append(entries, Entry[T]{Key: key, Value: value})
	}

	*o = entries
	return nil
}

// Get 按键取值。
func (o Ordered[T]) Get(key string) (T, bool) {
	for _, entry := range o {
		if entry.Key == key {
			return entry.Value, true
		}
	}
	var zero T
	return zero, false
}

// ── IR ───────────────────────────────────────────────────────────────

// Document 是一份 models.yaml 解析并校验后的结果。
type Document struct {
	// SourcePath 是配置文件的路径。
	SourcePath string    `yaml:"-"`
	Project    Project   `yaml:"project"`
	Database   Database  `yaml:"database"`
	Migration  Migration `yaml:"migration"`
	Models     []Model   `yaml:"models"`
	Targets    []Target  `yaml:"targets"`
	Mapping    Mapping   `yaml:"mapping"`
	// TopLevelVersion 是写在顶层的 version（v0.1 允许 project.version 与它二选一）。
	TopLevelVersion string `yaml:"version"`
}

// Project 是项目标识。
type Project struct {
	Name    string `yaml:"name"`
	Version string `yaml:"version"`
}

// Database 是数据库连接与方言信息。
type Database struct {
	URL      string `yaml:"url"`
	Dialect  string `yaml:"dialect"`
	PoolSize int    `yaml:"pool_size"`
	Echo     bool   `yaml:"echo"`
}

// Migration 是 v0.1 的迁移配置；v0.2 起由 Targets 表达，保留它是为了向后兼容。
type Migration struct {
	Directory string `yaml:"directory"`
	Template  string `yaml:"template"`
}

// Target 声明要把 schema 编译到哪个生态。
type Target struct {
	Name string `yaml:"name"`
	Kind string `yaml:"kind"` // alembic | atlas | flyway | plain-sql
	Dir  string `yaml:"dir"`
}

// Mapping 是第三方项目版本到数据库版本的映射。
type Mapping struct {
	ThirdParty []ThirdPartyMapping `yaml:"third_party"`
}

// ThirdPartyMapping 是一条第三方映射。
type ThirdPartyMapping struct {
	Project    string `yaml:"project"`
	Version    string `yaml:"version"`
	DBRevision string `yaml:"db_revision"`
}

// Model 是一个数据模型。
type Model struct {
	Name              string             `yaml:"name"`
	Table             string             `yaml:"table"`
	Description       string             `yaml:"description"`
	Module            string             `yaml:"module"`
	Unlogged          bool               `yaml:"unlogged"`
	Fields            []Field            `yaml:"fields"`
	Indexes           []Index            `yaml:"indexes"`
	UniqueConstraints []UniqueConstraint `yaml:"unique_constraints"`
	Relationships     []Relationship     `yaml:"relationships"`
}

// Field 是一个字段（列）。
type Field struct {
	// Name 是模型层的属性名（保留字会被改写成 extra_ 前缀）。
	Name string
	// Column 是数据库列名。
	Column string
	// ColumnExplicit 表示生成时必须显式写出列名。
	ColumnExplicit bool

	Type ColumnType

	Nullable      bool
	PrimaryKey    bool
	Autoincrement bool
	Unique        bool
	Index         bool

	// DefaultSQL 是已规范化的默认值源码片段（例如 func.now() / 'pending' / 0）。
	DefaultSQL string
	// DefaultImport 是使用默认值表达式时需要追加的 import 行。
	DefaultImport string

	Doc        string
	ForeignKey string
}

// ColumnType 是一个列类型。
type ColumnType struct {
	// Expression 是写进生成代码的类型表达式，例如 String(50) / JSONB。
	Expression string
	// ImportName 是需要导入的类型名，例如 JSONB。
	ImportName string
	// Module 是该类型所在的模块，例如 sqlalchemy.dialects.postgresql。
	Module string
	// Dialect 是方言名（空表示通用类型）。
	Dialect string
	// Components 是表达式内部还引用的类型（如 ARRAY(Text) 里的 Text）。
	Components []ColumnType
	// Generated 表示 SQLAlchemy 未内置、需要 Gefjon 生成 UserDefinedType 子类。
	Generated bool
}

// Index 是一个索引。
type Index struct {
	Name         string
	Columns      []string
	Unique       bool
	Using        string
	Ops          Ordered[string]
	WhereSQL     string
	Prefix       string
	Lengths      Ordered[int]
	Expressions  []string
	Concurrently bool
}

// UniqueConstraint 是一个唯一约束。
type UniqueConstraint struct {
	Name    string
	Columns []string
}

// Relationship 是一个 ORM 关系。
type Relationship struct {
	Name          string
	Target        string
	BackPopulates string
	Cascade       string
	Lazy          string
	// Uselist 为 nil 表示未指定（生成时不写出该参数）。
	Uselist   *bool
	Secondary string
}
