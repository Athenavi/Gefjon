package schema

import (
	"os"
	"path/filepath"
	"testing"
)

// goldenDir 指向前面的验收基准（与 Python 版共享同一批输入）。
func goldenDir() string {
	return filepath.Join("..", "..", "tests", "golden")
}

// TestLoadGoldenCases 用 golden 的三份输入验证解析结果。
func TestLoadGoldenCases(t *testing.T) {
	t.Run("basic", func(t *testing.T) {
		doc, err := Load(filepath.Join(goldenDir(), "basic", "models.yaml"))
		if err != nil {
			t.Fatalf("解析失败：%v", err)
		}

		if doc.Project.Name != "golden-basic" || doc.Project.Version != "1.0.0" {
			t.Errorf("project 解析错误：%+v", doc.Project)
		}
		if doc.Database.Dialect != "sqlite" {
			t.Errorf("dialect 解析错误：%q", doc.Database.Dialect)
		}
		if len(doc.Models) != 2 {
			t.Fatalf("模型数应为 2，得到 %d", len(doc.Models))
		}

		user := doc.Models[0]
		if user.Name != "User" || user.Table != "users" {
			t.Errorf("User 解析错误：%+v", user)
		}

		// 保留名 metadata 改写成 extra_metadata，但列名保持声明值
		last := user.Fields[len(user.Fields)-1]
		if last.Name != "extra_metadata" || last.Column != "metadata" || !last.ColumnExplicit {
			t.Errorf("保留名改写错误：%+v", last)
		}

		// 默认值走白名单并附带 import
		if user.Fields[3].DefaultSQL != "func.now()" {
			t.Errorf("默认值错误：%q", user.Fields[3].DefaultSQL)
		}
		if user.Fields[3].DefaultImport != "from sqlalchemy.sql import func" {
			t.Errorf("默认值 import 错误：%q", user.Fields[3].DefaultImport)
		}

		if len(user.Indexes) != 1 || user.Indexes[0].Name != "ix_users_email" || !user.Indexes[0].Unique {
			t.Errorf("索引解析错误：%+v", user.Indexes)
		}
		if len(user.UniqueConstraints) != 1 || user.UniqueConstraints[0].Name != "uq_users_email_username" {
			t.Errorf("唯一约束解析错误：%+v", user.UniqueConstraints)
		}

		post := doc.Models[1]
		if post.Module != "blog" {
			t.Errorf("module 解析错误：%q", post.Module)
		}
		if len(post.Relationships) != 1 {
			t.Fatalf("关系数应为 1，得到 %d", len(post.Relationships))
		}
		relation := post.Relationships[0]
		if relation.Name != "author" || relation.Target != "User" ||
			relation.BackPopulates != "posts" ||
			relation.Cascade != "all, delete-orphan" || relation.Lazy != "selectin" {
			t.Errorf("关系解析错误：%+v", relation)
		}
	})

	t.Run("postgres", func(t *testing.T) {
		doc, err := Load(filepath.Join(goldenDir(), "postgres", "models.yaml"))
		if err != nil {
			t.Fatalf("解析失败：%v", err)
		}

		model := doc.Models[0]
		if !model.Unlogged {
			t.Error("unlogged 应为 true")
		}

		byName := map[string]Field{}
		for _, field := range model.Fields {
			byName[field.Name] = field
		}

		checks := map[string]string{
			"payload":     "JSONB",
			"tags":        "ARRAY(Text)",
			"addr":        "INET",
			"uid":         "Uuid",
			"seen_at":     "TIMESTAMP(timezone=True)",
			"bits":        "BIT(8, varying=True)",
			"postal_code": "DOMAIN('us_postal_code', String(5), not_null=True)",
		}
		for name, want := range checks {
			if got := byName[name].Type.Expression; got != want {
				t.Errorf("%s 类型表达式 = %q, want %q", name, got, want)
			}
		}

		// SQLAlchemy 未内置的类型标记为需要生成
		shape := byName["shape"]
		if !shape.Type.Generated || shape.Type.ImportName != "POLYGON" ||
			shape.Type.Module != ModulePostgreSQL {
			t.Errorf("udt 类型解析错误：%+v", shape.Type)
		}

		if len(model.Indexes) != 3 {
			t.Fatalf("索引数应为 3，得到 %d", len(model.Indexes))
		}
		if model.Indexes[0].Using != "gin" {
			t.Errorf("using 解析错误：%q", model.Indexes[0].Using)
		}
		if ops := model.Indexes[0].Ops; len(ops) != 1 || ops[0].Key != "payload" || ops[0].Value != "jsonb_path_ops" {
			t.Errorf("ops 解析错误：%+v", ops)
		}
		if model.Indexes[1].WhereSQL != "addr IS NOT NULL" {
			t.Errorf("where 解析错误：%q", model.Indexes[1].WhereSQL)
		}
		if expressions := model.Indexes[2].Expressions; len(expressions) != 1 || expressions[0] != "lower(payload)" {
			t.Errorf("expressions 解析错误：%+v", expressions)
		}
		if !model.Indexes[2].Concurrently {
			t.Error("concurrently 应为 true")
		}
	})

	t.Run("mysql", func(t *testing.T) {
		doc, err := Load(filepath.Join(goldenDir(), "mysql", "models.yaml"))
		if err != nil {
			t.Fatalf("解析失败：%v", err)
		}

		byName := map[string]Field{}
		for _, field := range doc.Models[0].Fields {
			byName[field.Name] = field
		}
		if got := byName["flags"].Type.Expression; got != "SET('a', 'b', 'c')" {
			t.Errorf("SET 类型表达式 = %q", got)
		}
		if got := byName["price"].Type.Expression; got != "DECIMAL(10, 2)" {
			t.Errorf("DECIMAL 类型表达式 = %q", got)
		}

		indexes := doc.Models[0].Indexes
		if len(indexes) != 2 {
			t.Fatalf("索引数应为 2，得到 %d", len(indexes))
		}
		if indexes[0].Prefix != "fulltext" {
			t.Errorf("prefix 解析错误：%q", indexes[0].Prefix)
		}
		if lengths := indexes[1].Lengths; len(lengths) != 1 || lengths[0].Key != "sku" || lengths[0].Value != 32 {
			t.Errorf("lengths 解析错误：%+v", lengths)
		}
	})
}

// writeConfig 把 YAML 写进临时文件后加载。
func writeConfig(t *testing.T, body string) (*Document, error) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "models.yaml")
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatalf("写入临时配置失败：%v", err)
	}
	return Load(path)
}

// TestValidationRules 覆盖 v0.1 的校验规则（含若干注入尝试）。
func TestValidationRules(t *testing.T) {
	cases := []struct {
		name string
		body string
		want string
	}{
		{
			name: "非法字段名",
			body: "models:\n  - name: Thing\n    fields:\n      - name: \"x = 1; import os\"\n        type: Integer\n",
			want: "不是合法的 Python 标识符",
		},
		{
			name: "未知类型",
			body: "models:\n  - name: Thing\n    fields:\n      - name: v\n        type: NoSuchType\n",
			want: "不支持的类型",
		},
		{
			name: "default 注入",
			body: "models:\n  - name: Thing\n    fields:\n      - name: v\n        type: String(10)\n        default: \"os.system('id')\"\n",
			want: "白名单",
		},
		{
			name: "where 注入",
			body: "models:\n  - name: Thing\n    fields:\n      - name: v\n        type: Integer\n    indexes:\n      - columns: [v]\n        where: \"1=1; DROP TABLE t\"\n",
			want: "不允许出现",
		},
		{
			name: "表达式函数白名单",
			body: "models:\n  - name: Thing\n    fields:\n      - name: v\n        type: String(10)\n    indexes:\n      - expressions: [\"evil(v)\"]\n",
			want: "不支持的索引函数",
		},
		{
			name: "cascade 白名单",
			body: "models:\n  - name: Thing\n    fields:\n      - name: id\n        type: Integer\n        primary_key: true\n    relationships:\n      - name: kids\n        target: Thing\n        cascade: \"all, DROP TABLE t\"\n",
			want: "cascade",
		},
		{
			name: "back_populates 不存在",
			body: "models:\n  - name: A\n    fields:\n      - name: id\n        type: Integer\n        primary_key: true\n    relationships:\n      - name: bs\n        target: B\n        back_populates: missing\n  - name: B\n    fields:\n      - name: id\n        type: Integer\n        primary_key: true\n",
			want: "back_populates",
		},
		{
			name: "歧义类型需要前缀",
			body: "models:\n  - name: Thing\n    fields:\n      - name: v\n        type: BIT\n",
			want: "含义不同",
		},
		{
			name: "复合唯一约束引用不存在的字段",
			body: "models:\n  - name: Thing\n    fields:\n      - name: id\n        type: Integer\n        primary_key: true\n    unique_constraints:\n      - name: uq\n        columns: [nope]\n",
			want: "不存在的字段",
		},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			_, err := writeConfig(t, testCase.body)
			if err == nil {
				t.Fatalf("期望报错，实际解析成功")
			}
			if !contains(err.Error(), testCase.want) {
				t.Fatalf("错误信息 %q 未包含 %q", err.Error(), testCase.want)
			}
		})
	}
}

// TestDialectResolvesAmbiguity 验证 database.dialect 能消解同名类型。
func TestDialectResolvesAmbiguity(t *testing.T) {
	doc, err := writeConfig(t, `database:
  dialect: mysql
models:
  - name: Thing
    fields:
      - name: v
        type: BIT
`)
	if err != nil {
		t.Fatalf("解析失败：%v", err)
	}
	field := doc.Models[0].Fields[0]
	if field.Type.Module != ModuleMySQL {
		t.Errorf("dialect=mysql 时 BIT 应解析为 MySQL 类型，得到 %q", field.Type.Module)
	}
}

func contains(haystack, needle string) bool {
	return len(needle) == 0 || (len(haystack) >= len(needle) && indexOf(haystack, needle) >= 0)
}

func indexOf(haystack, needle string) int {
	for i := 0; i+len(needle) <= len(haystack); i++ {
		if haystack[i:i+len(needle)] == needle {
			return i
		}
	}
	return -1
}
