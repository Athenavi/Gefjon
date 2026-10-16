package render

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/Athenavi/Gefjon/internal/schema"
)

func goldenCases() []string {
	return []string{"basic", "postgres", "mysql"}
}

// TestPackageFilesMatchGolden 是 m1_generate 的核心验收：
// Go 版渲染出的每个文件都必须与 v0.1 固化的 golden fixtures **逐字节一致**。
func TestPackageFilesMatchGolden(t *testing.T) {
	for _, name := range goldenCases() {
		t.Run(name, func(t *testing.T) {
			root := filepath.Join("..", "..", "tests", "golden", name)

			doc, err := schema.Load(filepath.Join(root, "models.yaml"))
			if err != nil {
				t.Fatalf("解析输入失败：%v", err)
			}

			files := PackageFiles(doc.Models)
			expected := readGoldenDir(t, filepath.Join(root, "models"))

			if len(files) != len(expected) {
				t.Fatalf("文件集合不一致\nGo: %v\ngolden: %v",
					sortedPaths(files), sortedPaths(expected))
			}

			for path, want := range expected {
				got, ok := files[path]
				if !ok {
					t.Errorf("Go 版缺少文件 %s", path)
					continue
				}
				if got != want {
					t.Errorf("%s 与 golden 不一致（Go %d 字节 / golden %d 字节）\n%s",
						path, len(got), len(want), firstDifference(got, want))
				}
			}
		})
	}
}

func readGoldenDir(t *testing.T, root string) map[string]string {
	t.Helper()

	files := map[string]string{}
	err := filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if info.IsDir() {
			return nil
		}
		relative, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		files[filepath.ToSlash(relative)] = string(data)
		return nil
	})
	if err != nil {
		t.Fatalf("读取 golden 失败：%v", err)
	}
	return files
}

func sortedPaths(files map[string]string) []string {
	paths := make([]string, 0, len(files))
	for path := range files {
		paths = append(paths, path)
	}
	strings.Join(paths, ",") // 仅为可读性，排序交给下面
	sortStrings(paths)
	return paths
}

// firstDifference 只报告首个不同的行，避免把整个文件倾泻到测试输出里。
func firstDifference(got, want string) string {
	gotLines := strings.Split(got, "\n")
	wantLines := strings.Split(want, "\n")

	for i := 0; i < len(gotLines) || i < len(wantLines); i++ {
		var gotLine, wantLine string
		if i < len(gotLines) {
			gotLine = gotLines[i]
		}
		if i < len(wantLines) {
			wantLine = wantLines[i]
		}
		if gotLine != wantLine {
			return fmt.Sprintf("第 %d 行不同：\n  Go     : %q\n  golden : %q",
				i+1, gotLine, wantLine)
		}
	}
	return "(各行内容相同，差异可能在结尾换行)"
}

func sortStrings(values []string) {
	for i := 1; i < len(values); i++ {
		for j := i; j > 0 && values[j] < values[j-1]; j-- {
			values[j], values[j-1] = values[j-1], values[j]
		}
	}
}
