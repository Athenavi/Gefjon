package detect

import (
	"os"
	"path/filepath"
	"testing"
)

func touch(t *testing.T, dir, name string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(dir, name), []byte("x\n"), 0o600); err != nil {
		t.Fatal(err)
	}
}

func TestDetectGoProject(t *testing.T) {
	dir := t.TempDir()
	touch(t, dir, "go.mod")

	got := Detect(dir)
	if len(got) != 1 || got[0].Kind != KindAtlas {
		t.Fatalf("期望推荐 atlas，得到 %+v", got)
	}
	if got[0].Dir != "db/migrations" {
		t.Errorf("默认目录应为 db/migrations，得到 %q", got[0].Dir)
	}
	if len(got[0].Evidence) != 1 || got[0].Evidence[0] != "go.mod" {
		t.Errorf("证据应为 go.mod，得到 %v", got[0].Evidence)
	}
}

func TestDetectOtherStacks(t *testing.T) {
	cases := []struct {
		file string
		want Kind
	}{
		{"pyproject.toml", KindAlembic},
		{"requirements.txt", KindAlembic},
		{"pom.xml", KindFlyway},
		{"build.gradle.kts", KindFlyway},
		{"package.json", KindPlainSQL},
	}
	for _, testCase := range cases {
		t.Run(testCase.file, func(t *testing.T) {
			dir := t.TempDir()
			touch(t, dir, testCase.file)

			got := Detect(dir)
			if len(got) != 1 || got[0].Kind != testCase.want {
				t.Fatalf("文件 %s 应推荐 %s，得到 %+v", testCase.file, testCase.want, got)
			}
		})
	}
}

func TestDetectMultiStackKeepsRuleOrder(t *testing.T) {
	dir := t.TempDir()
	touch(t, dir, "go.mod")
	touch(t, dir, "pyproject.toml")

	got := Detect(dir)
	if len(got) != 2 || got[0].Kind != KindAtlas || got[1].Kind != KindAlembic {
		t.Fatalf("期望顺序 [atlas, alembic]，得到 %+v", got)
	}
}

func TestDetectEmptyProjectFallsBackToPlainSQL(t *testing.T) {
	got := Detect(t.TempDir())
	if len(got) != 1 || got[0].Kind != KindPlainSQL {
		t.Fatalf("空项目应给出 plain-sql 默认项，得到 %+v", got)
	}
	if got[0].Reason == "" {
		t.Error("默认项也应当有理由")
	}
}

func TestKnownKinds(t *testing.T) {
	for _, kind := range KnownKinds() {
		if !IsKnown(kind) {
			t.Errorf("%q 应当是已知后端", kind)
		}
		if DefaultDir(kind) == "" {
			t.Errorf("%q 缺少默认目录", kind)
		}
	}
	if IsKnown("nope") {
		t.Error("未知后端不应被接受")
	}
}
