package state

import (
	"os"
	"strings"
	"testing"
)

func TestLoadMissingReturnsNil(t *testing.T) {
	got, err := Load(t.TempDir())
	if err != nil || got != nil {
		t.Fatalf("状态文件缺失时应返回 (nil, nil)，得到 (%v, %v)", got, err)
	}
}

func TestSaveLoadRoundTrip(t *testing.T) {
	root := t.TempDir()
	want := &State{
		Targets: []Target{{Kind: "atlas", Dir: "db/migrations"}},
		Baselines: []Baseline{{
			Target: "atlas", AdoptedFrom: "alembic_version",
			Revision: "ab12cd34", At: "2026-10-16T00:00:00Z",
		}},
	}

	if err := Save(root, want); err != nil {
		t.Fatalf("保存失败：%v", err)
	}

	got, err := Load(root)
	if err != nil {
		t.Fatalf("读取失败：%v", err)
	}
	if got.SchemaVersion != SchemaVersion {
		t.Errorf("schema_version = %d，want %d", got.SchemaVersion, SchemaVersion)
	}
	if len(got.Targets) != 1 || got.Targets[0].Kind != "atlas" {
		t.Errorf("targets 往返错误：%+v", got.Targets)
	}
	if len(got.Baselines) != 1 || got.Baselines[0].AdoptedFrom != "alembic_version" {
		t.Errorf("baselines 往返错误：%+v", got.Baselines)
	}
}

func TestSavedFileUsesLFAndTrailingNewline(t *testing.T) {
	root := t.TempDir()
	if err := Save(root, &State{Targets: []Target{{Kind: "alembic", Dir: "migrations"}}}); err != nil {
		t.Fatal(err)
	}

	data, err := os.ReadFile(Path(root))
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(data), "\r") {
		t.Error("状态文件不应包含 CR（跨平台一致性）")
	}
	if !strings.HasSuffix(string(data), "\n") {
		t.Error("状态文件应以换行结尾")
	}
}

func TestFindTarget(t *testing.T) {
	current := &State{Targets: []Target{{Kind: "atlas", Dir: "db/migrations"}}}

	if _, ok := current.FindTarget("atlas"); !ok {
		t.Error("应当能找到 atlas")
	}
	if _, ok := current.FindTarget("flyway"); ok {
		t.Error("不应当找到 flyway")
	}
}
