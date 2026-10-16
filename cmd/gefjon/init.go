package main

import (
	"bufio"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/Athenavi/Gefjon/internal/assets"
	"github.com/Athenavi/Gefjon/internal/detect"
	"github.com/Athenavi/Gefjon/internal/schema"
	"github.com/Athenavi/Gefjon/internal/state"
)

// runInit 实现 `gefjon init`：探测技术栈 -> 推荐后端 -> 生成配置与状态。
//
// 设计原则（见 docs/v0.2-go-binary-design.md）：不做静默猜测 ——
// 探测结果与推荐理由都打印出来，交互场景让用户确认，CI 场景用 --yes。
func runInit(args []string) error {
	flags := flag.NewFlagSet("init", flag.ContinueOnError)
	assumeYes := flags.Bool("yes", false, "不交互，直接采用探测到的首选推荐")
	kind := flags.String("kind", "", "显式指定后端（atlas / alembic / flyway / plain-sql）")
	output := flags.String("output", "", "模型包目录（默认 models）")
	dir := flags.String("dir", "", "该后端的产物目录（默认按后端决定）")
	force := flags.Bool("force", false, "覆盖已存在的 models.yaml")
	if err := flags.Parse(args); err != nil {
		return err
	}

	root, err := os.Getwd()
	if err != nil {
		return err
	}

	choice, err := chooseBackend(root, *kind, *assumeYes)
	if err != nil {
		return err
	}

	modelDir := *output
	if modelDir == "" {
		modelDir = schema.DefaultOutputDir
	}
	targetDir := *dir
	if targetDir == "" {
		targetDir = choice.Dir
	}

	fmt.Println()
	if err := writeIfAbsent(filepath.Join(root, "models.yaml"), assets.SampleModels, *force); err != nil {
		return err
	}

	// 后端产物目录先建出来；具体脚手架由各后端在后续里程碑生成
	absoluteTargetDir := filepath.Join(root, filepath.FromSlash(targetDir))
	if err := os.MkdirAll(absoluteTargetDir, 0o755); err != nil {
		return fmt.Errorf("创建 %s 失败：%v", absoluteTargetDir, err)
	}

	current, err := state.Load(root)
	if err != nil {
		return err
	}
	if current == nil {
		current = &state.State{}
	}
	current.Targets = upsertTarget(current.Targets, state.Target{
		Kind: string(choice.Kind),
		Dir:  targetDir,
	})
	if err := state.Save(root, current); err != nil {
		return err
	}

	fmt.Printf("  后端：%s（产物目录 %s）\n", choice.Kind, targetDir)
	fmt.Printf("  模型包目录：%s\n", modelDir)
	fmt.Printf("  状态文件：%s\n", state.Path(root))
	fmt.Println()
	fmt.Println("下一步：编辑 models.yaml，然后运行 `gefjon generate`")
	return nil
}

// chooseBackend 决定用哪个后端：显式指定 > 探测（交互确认或取首选）。
func chooseBackend(root, kind string, assumeYes bool) (detect.Recommendation, error) {
	if kind != "" {
		choice := detect.Kind(kind)
		if !detect.IsKnown(choice) {
			return detect.Recommendation{}, fmt.Errorf(
				"未知后端 %q；可用：%s", kind, joinKinds(detect.KnownKinds()))
		}
		return detect.Recommendation{
			Kind:   choice,
			Dir:    detect.DefaultDir(choice),
			Reason: "由 --kind 显式指定",
		}, nil
	}

	found := detect.Detect(root)
	printRecommendations(found)

	if assumeYes || !isInteractive() {
		fmt.Printf("采用首选推荐：%s\n", found[0].Kind)
		return found[0], nil
	}
	if len(found) == 1 {
		return found[0], nil
	}
	return promptChoice(found)
}

func printRecommendations(found []detect.Recommendation) {
	fmt.Println("检测到以下技术栈：")
	for index, item := range found {
		marker := "  "
		if index == 0 {
			marker = "→ "
		}
		fmt.Printf("%s%d) %-9s %s\n", marker, index+1, item.Kind, item.Reason)
		if len(item.Evidence) > 0 {
			fmt.Printf("      证据：%s\n", strings.Join(item.Evidence, ", "))
		}
	}
}

func promptChoice(found []detect.Recommendation) (detect.Recommendation, error) {
	fmt.Print("选择后端 [1]: ")
	line, _ := bufio.NewReader(os.Stdin).ReadString('\n')
	line = strings.TrimSpace(line)
	if line == "" {
		return found[0], nil
	}

	index, err := strconv.Atoi(line)
	if err != nil || index < 1 || index > len(found) {
		return detect.Recommendation{}, fmt.Errorf("无效的选择：%q", line)
	}
	return found[index-1], nil
}

// isInteractive 判断是否连着终端：CI / 管道场景下不应阻塞等待输入。
func isInteractive() bool {
	info, err := os.Stdin.Stat()
	if err != nil {
		return false
	}
	return info.Mode()&os.ModeCharDevice != 0
}

func writeIfAbsent(path, content string, force bool) error {
	if _, err := os.Stat(path); err == nil && !force {
		fmt.Printf("  已存在，跳过：%s\n", filepath.Base(path))
		return nil
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		return fmt.Errorf("写入 %s 失败：%v", path, err)
	}
	fmt.Printf("  已创建：%s\n", filepath.Base(path))
	return nil
}

func upsertTarget(targets []state.Target, candidate state.Target) []state.Target {
	for index, target := range targets {
		if target.Kind == candidate.Kind {
			targets[index] = candidate
			return targets
		}
	}
	return append(targets, candidate)
}

func joinKinds(kinds []detect.Kind) string {
	parts := make([]string, 0, len(kinds))
	for _, item := range kinds {
		parts = append(parts, string(item))
	}
	return strings.Join(parts, " / ")
}
