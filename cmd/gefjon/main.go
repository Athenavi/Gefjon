// Command gefjon 是 Gefjon 的命令行入口。
//
// Gefjon 以 models.yaml 为唯一权威，把它编译成各生态的 schema 产物；
// 连库、算 diff 与执行迁移交给该生态的原生工具（alembic / atlas / flyway）。
// 因此本二进制不含任何数据库驱动，可以做到很小、且无需任何运行时环境。
//
// 设计见 docs/v0.2-go-binary-design.md。
package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/Athenavi/Gefjon/internal/assets"
	"github.com/Athenavi/Gefjon/internal/console"
	"github.com/Athenavi/Gefjon/internal/render"
	"github.com/Athenavi/Gefjon/internal/schema"
	"github.com/Athenavi/Gefjon/internal/version"
)

func main() {
	// Windows 控制台默认按本地代码页解码，需先切到 UTF-8 才能正常显示中文
	console.EnableUTF8()

	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "错误："+err.Error())
		os.Exit(1)
	}
}

func run(args []string) error {
	if len(args) == 0 {
		usage()
		return nil
	}

	switch args[0] {
	case "version", "--version", "-v":
		info := version.Get()
		fmt.Printf("gefjon %s (commit %s, built %s)\n", info.Version, info.Commit, info.BuildDate)
		return nil

	case "generate":
		return runGenerate(args[1:])

	case "init":
		return runInit(args[1:])

	case "sample-config":
		fmt.Print(assets.SampleModels)
		return nil

	case "help", "--help", "-h":
		usage()
		return nil

	default:
		return fmt.Errorf("未知命令 %q", args[0])
	}
}

func usage() {
	fmt.Print(`gefjon —— 以 models.yaml 为唯一权威的 schema 编排器

用法：
  gefjon <命令> [选项]

命令：
  generate [--check] [--output DIR] [--config FILE]
                 按 models.yaml 生成模型代码；--check 只校验是否一致
  version        显示版本
  sample-config  打印内置的示例 models.yaml
  help           显示本帮助

详见 docs/v0.2-go-binary-design.md。
`)
}

func runGenerate(args []string) error {
	flags := flag.NewFlagSet("generate", flag.ContinueOnError)
	checkOnly := flags.Bool("check", false, "只校验模型包是否与 models.yaml 一致，不写文件")
	output := flags.String("output", "", "模型包输出目录（默认 models）")
	configPath := flags.String("config", "models.yaml", "models.yaml 路径")
	if err := flags.Parse(args); err != nil {
		return err
	}

	document, err := schema.Load(*configPath)
	if err != nil {
		return err
	}

	target := *output
	if target == "" {
		target = schema.DefaultOutputDir
	}

	files := render.PackageFiles(document.Models)
	if *checkOnly {
		return checkPackage(target, files)
	}
	return writePackage(target, files)
}

func writePackage(target string, files map[string]string) error {
	for _, relative := range sortedKeys(files) {
		path := filepath.Join(target, filepath.FromSlash(relative))
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			return err
		}
		// 始终写 LF：产物跨平台一致
		if err := os.WriteFile(path, []byte(files[relative]), 0o644); err != nil {
			return err
		}
	}
	fmt.Printf("已生成 %d 个文件：%s\n", len(files), target)
	return nil
}

// checkPackage 是 generate --check 的实现：只读，列出三类差异后以错误结束。
func checkPackage(target string, files map[string]string) error {
	var missing, changed []string
	for _, relative := range sortedKeys(files) {
		path := filepath.Join(target, filepath.FromSlash(relative))
		data, err := os.ReadFile(path)
		if err != nil {
			missing = append(missing, relative)
			continue
		}
		if string(data) != files[relative] {
			changed = append(changed, relative)
		}
	}

	var extra []string
	_ = filepath.Walk(target, func(path string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() || !strings.HasSuffix(path, ".py") {
			return nil
		}
		relative, err := filepath.Rel(target, path)
		if err != nil {
			return nil
		}
		key := filepath.ToSlash(relative)
		if _, known := files[key]; !known {
			extra = append(extra, key)
		}
		return nil
	})

	if len(missing) == 0 && len(changed) == 0 && len(extra) == 0 {
		fmt.Printf("模型包与 models.yaml 一致：%s\n", target)
		return nil
	}

	sort.Strings(missing)
	sort.Strings(changed)
	sort.Strings(extra)
	for _, path := range missing {
		fmt.Println("  缺失：", path)
	}
	for _, path := range changed {
		fmt.Println("  不一致：", path)
	}
	for _, path := range extra {
		fmt.Println("  多余：", path)
	}
	return fmt.Errorf("模型包与 models.yaml 不一致，请运行 gefjon generate")
}

func sortedKeys(files map[string]string) []string {
	keys := make([]string, 0, len(files))
	for key := range files {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}
