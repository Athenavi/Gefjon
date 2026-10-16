// Package state 读写 .gefjon/state.json —— Gefjon 在项目里的状态文件。
//
// 记录：本项目要编译到哪些后端（targets）、各自最后应用的 revision，
// 以及从别的迁移工具「接力」时留下的 baseline 记录。
package state

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

const (
	// DirName 是状态目录名。
	DirName = ".gefjon"
	// FileName 是状态文件名。
	FileName = "state.json"
	// SchemaVersion 是当前状态文件的格式版本。
	SchemaVersion = 1
)

// Target 是一个已配置的编译目标。
type Target struct {
	Kind         string `json:"kind"`
	Dir          string `json:"dir"`
	LastRevision string `json:"last_revision,omitempty"`
}

// Baseline 记录一次版本接力（从别的迁移工具接管）。
type Baseline struct {
	Target      string `json:"target"`
	AdoptedFrom string `json:"adopted_from"`
	Revision    string `json:"revision"`
	At          string `json:"at"`
}

// State 是状态文件的完整内容。
type State struct {
	SchemaVersion int        `json:"schema_version"`
	Targets       []Target   `json:"targets"`
	Baselines     []Baseline `json:"baselines,omitempty"`
}

// Path 返回状态文件的路径。
func Path(root string) string {
	return filepath.Join(root, DirName, FileName)
}

// Load 读取状态文件；不存在时返回 (nil, nil)，便于调用方区分「没初始化」。
func Load(root string) (*State, error) {
	path := Path(root)

	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("读取 %s 失败：%v", path, err)
	}

	var state State
	if err := json.Unmarshal(data, &state); err != nil {
		return nil, fmt.Errorf("%s 不是合法 JSON：%v", path, err)
	}
	if state.SchemaVersion == 0 {
		state.SchemaVersion = SchemaVersion
	}
	return &state, nil
}

// Save 原子写入状态文件（临时文件 + rename，内容用 LF）。
func Save(root string, state *State) error {
	if state.SchemaVersion == 0 {
		state.SchemaVersion = SchemaVersion
	}

	payload, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return fmt.Errorf("序列化状态失败：%v", err)
	}
	payload = append(payload, '\n')

	dir := filepath.Join(root, DirName)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return fmt.Errorf("创建 %s 失败：%v", dir, err)
	}

	target := filepath.Join(dir, FileName)
	tmp := target + ".tmp"
	if err := os.WriteFile(tmp, payload, 0o644); err != nil {
		return fmt.Errorf("写入 %s 失败：%v", tmp, err)
	}
	if err := os.Rename(tmp, target); err != nil {
		_ = os.Remove(tmp)
		return fmt.Errorf("替换 %s 失败：%v", target, err)
	}
	return nil
}

// FindTarget 按 kind 查找目标。
func (s *State) FindTarget(kind string) (Target, bool) {
	for _, target := range s.Targets {
		if target.Kind == kind {
			return target, true
		}
	}
	return Target{}, false
}
