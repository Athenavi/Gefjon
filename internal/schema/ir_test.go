package schema

import (
	"testing"

	"gopkg.in/yaml.v3"
)

func TestOrderedPreservesYAMLOrder(t *testing.T) {
	var parsed struct {
		Ops Ordered[string] `yaml:"ops"`
	}
	// 故意用非字典序，以证明顺序来自 YAML 而非排序
	source := "ops:\n  zulu: two\n  alpha: one\n  mike: three\n"

	if err := yaml.Unmarshal([]byte(source), &parsed); err != nil {
		t.Fatalf("解析失败：%v", err)
	}

	got := make([]string, 0, len(parsed.Ops))
	for _, entry := range parsed.Ops {
		got = append(got, entry.Key+"="+entry.Value)
	}
	want := []string{"zulu=two", "alpha=one", "mike=three"}

	if len(got) != len(want) {
		t.Fatalf("条目数不符：got %v", got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("顺序被破坏：got %v, want %v", got, want)
		}
	}
}

func TestOrderedSupportsNonStringValues(t *testing.T) {
	var parsed struct {
		Lengths Ordered[int] `yaml:"lengths"`
	}
	if err := yaml.Unmarshal([]byte("lengths:\n  url: 191\n  sku: 32\n"), &parsed); err != nil {
		t.Fatalf("解析失败：%v", err)
	}
	if value, ok := parsed.Lengths.Get("url"); !ok || value != 191 {
		t.Fatalf("取值失败：%v %v", value, ok)
	}
	if _, ok := parsed.Lengths.Get("missing"); ok {
		t.Fatal("不存在的键不该返回 ok")
	}
}

func TestOrderedRejectsNonMapping(t *testing.T) {
	var parsed struct {
		Ops Ordered[string] `yaml:"ops"`
	}
	if err := yaml.Unmarshal([]byte("ops:\n  - a\n  - b\n"), &parsed); err == nil {
		t.Fatal("序列不是映射，应当报错")
	}
}

func TestOrderedEmptyMapping(t *testing.T) {
	var parsed struct {
		Ops Ordered[string] `yaml:"ops"`
	}
	if err := yaml.Unmarshal([]byte("ops: {}\n"), &parsed); err != nil {
		t.Fatalf("解析空映射失败：%v", err)
	}
	if len(parsed.Ops) != 0 {
		t.Fatalf("空映射应为空：%v", parsed.Ops)
	}
}
