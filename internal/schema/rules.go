package schema

import (
	"fmt"
	"regexp"
	"strings"
)

// ── 索引选项白名单 ───────────────────────────────────────────────────

// pgIndexMethods 是 PostgreSQL 的 CREATE INDEX ... USING 方法。
var pgIndexMethods = map[string]bool{
	"btree": true, "hash": true, "gist": true,
	"gin": true, "brin": true, "spgist": true,
}

// mysqlIndexPrefixes 是 MySQL 的索引前缀类型。
var mysqlIndexPrefixes = map[string]bool{"fulltext": true, "spatial": true}

var opclassPattern = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$`)

// ── 部分索引条件（index.where）───────────────────────────────────────
//
// 只接受「列 IS [NOT] NULL」与「列 比较符 字面量」，用 AND/OR 连接；
// 解析后按结构化结果重新拼装，用户输入不会以原始形式进入 SQL。

var (
	whereTermNullPattern = regexp.MustCompile(
		`(?i)^([A-Za-z_][A-Za-z0-9_]*)\s+IS\s+(NOT\s+)?NULL$`)
	whereTermComparisonPattern = regexp.MustCompile(
		`^([A-Za-z_][A-Za-z0-9_]*)\s*(<=|>=|<>|!=|=|<|>)\s*(.+)$`)
	whereLiteralNumberPattern = regexp.MustCompile(`^-?\d+(?:\.\d+)?$`)
	whereLiteralBoolPattern   = regexp.MustCompile(`(?i)^(true|false|null)$`)
	whereLiteralStringPattern = regexp.MustCompile(`^'(?:[^']|'')*'$`)
	whereJoinPattern          = regexp.MustCompile(`(?i)\s+(AND|OR)\s+`)
)

var whereForbidden = []string{";", "--", "/*", "*/", "(", ")", ","}

// ── 表达式索引 ───────────────────────────────────────────────────────

var allowedIndexFunctions = map[string]bool{
	"lower": true, "upper": true, "trim": true, "ltrim": true, "rtrim": true,
	"length": true, "abs": true, "date": true, "md5": true,
}

var indexExpressionPattern = regexp.MustCompile(
	`^(?:(?P<func>[A-Za-z_][A-Za-z0-9_]*)\((?P<arg>[A-Za-z_][A-Za-z0-9_]*)\)` +
		`|(?P<plain>[A-Za-z_][A-Za-z0-9_]*))$`)

// ── relationship 白名单 ──────────────────────────────────────────────

var allowedCascades = map[string]bool{
	"save-update": true, "merge": true, "expunge": true, "delete": true,
	"delete-orphan": true, "no-delete-orphan": true, "refresh-expire": true,
	"all": true,
}

var allowedLazy = map[string]bool{
	"select": true, "joined": true, "subquery": true, "selectin": true,
	"immediate": true, "noload": true, "raise": true, "raise_on_sql": true,
	"write_only": true, "dynamic": true,
}

// ── 列引用校验 ───────────────────────────────────────────────────────

// validateColumns 校验列引用存在，并返回用户书写的列名（用于生成 Index/Constraint）。
func validateColumns(raw []any, fieldNames map[string]struct{}, kind string) ([]string, error) {
	resolved := make([]string, 0, len(raw))

	for _, item := range raw {
		column, ok := item.(string)
		if !ok || !IsValidIdentifier(column) {
			return nil, fmt.Errorf("%s 的列名 %v 不是合法的字段名", kind, item)
		}

		attribute := column
		if isReserved(column) {
			attribute = "extra_" + column
		}
		if _, exists := fieldNames[attribute]; !exists {
			return nil, fmt.Errorf("%s 引用了不存在的字段 %q；可用字段：%s",
				kind, column, sortedFieldNames(fieldNames))
		}
		resolved = append(resolved, column)
	}
	return resolved, nil
}

// ── 索引 ─────────────────────────────────────────────────────────────

func parseIndexes(raw []yamlIndex, table string, fieldNames map[string]struct{}) ([]Index, error) {
	if len(raw) == 0 {
		return nil, nil
	}

	indexes := make([]Index, 0, len(raw))
	for _, entry := range raw {
		expressions, err := parseIndexExpressions(entry.Expressions, fieldNames)
		if err != nil {
			return nil, err
		}

		var columns []string
		if len(entry.Columns) > 0 {
			columns, err = validateColumns(entry.Columns, fieldNames, "index")
			if err != nil {
				return nil, err
			}
		}
		if len(columns) == 0 && len(expressions) == 0 {
			return nil, fmt.Errorf("index 必须提供非空的 columns 或 expressions")
		}

		name := entry.Name
		switch {
		case name != "":
		case len(columns) > 0:
			name = fmt.Sprintf("ix_%s_%s", table, strings.Join(columns, "_"))
		default:
			name = fmt.Sprintf("ix_%s_%s", table, slugify(expressions))
		}

		using := strings.ToLower(strings.TrimSpace(entry.Using))
		if using != "" && !pgIndexMethods[using] {
			return nil, fmt.Errorf("index 的 using 只支持 %s，收到 %q",
				strings.Join(sortedKeys(pgIndexMethods), ", "), entry.Using)
		}

		prefix := strings.ToLower(strings.TrimSpace(entry.Prefix))
		if prefix != "" && !mysqlIndexPrefixes[prefix] {
			return nil, fmt.Errorf("index 的 prefix 只支持 %s，收到 %q",
				strings.Join(sortedKeys(mysqlIndexPrefixes), ", "), entry.Prefix)
		}

		concurrently := false
		if entry.Concurrently != nil {
			concurrently = *entry.Concurrently
		}

		whereSQL := ""
		if strings.TrimSpace(entry.Where) != "" {
			whereSQL, err = normalizePartialWhere(entry.Where, columns)
			if err != nil {
				return nil, err
			}
		}

		ops, err := parseIndexOps(entry.Ops, columns)
		if err != nil {
			return nil, err
		}
		lengths, err := parseIndexLengths(entry.Lengths, columns)
		if err != nil {
			return nil, err
		}

		indexes = append(indexes, Index{
			Name:         name,
			Columns:      columns,
			Unique:       entry.Unique,
			Using:        using,
			Ops:          ops,
			WhereSQL:     whereSQL,
			Prefix:       prefix,
			Lengths:      lengths,
			Expressions:  expressions,
			Concurrently: concurrently,
		})
	}
	return indexes, nil
}

func parseIndexOps(raw Ordered[string], columns []string) (Ordered[string], error) {
	if len(raw) == 0 {
		return nil, nil
	}

	result := make(Ordered[string], 0, len(raw))
	for _, entry := range raw {
		if !containsString(columns, entry.Key) {
			return nil, fmt.Errorf("index 的 ops 引用了不在 columns 里的列 %q", entry.Key)
		}
		if !opclassPattern.MatchString(entry.Value) {
			return nil, fmt.Errorf(
				"index 的操作符类 %q 非法（只允许标识符，可带模式前缀）", entry.Value)
		}
		result = append(result, entry)
	}
	return result, nil
}

func parseIndexLengths(raw Ordered[int], columns []string) (Ordered[int], error) {
	if len(raw) == 0 {
		return nil, nil
	}

	result := make(Ordered[int], 0, len(raw))
	for _, entry := range raw {
		if !containsString(columns, entry.Key) {
			return nil, fmt.Errorf("index 的 lengths 引用了不在 columns 里的列 %q", entry.Key)
		}
		if entry.Value <= 0 {
			return nil, fmt.Errorf("index 的 lengths[%s] 必须是正整数", entry.Key)
		}
		result = append(result, entry)
	}
	return result, nil
}

// parseIndexExpressions 解析表达式索引：只允许 列名 或 白名单函数(列名)。
func parseIndexExpressions(raw []any, fieldNames map[string]struct{}) ([]string, error) {
	if raw == nil {
		return nil, nil
	}
	if len(raw) == 0 {
		return nil, fmt.Errorf("index 的 expressions 必须是非空列表")
	}

	result := make([]string, 0, len(raw))
	for _, item := range raw {
		expression, ok := item.(string)
		if !ok || strings.TrimSpace(expression) == "" {
			return nil, fmt.Errorf("index 的表达式必须是非空字符串：%v", item)
		}
		expression = strings.TrimSpace(expression)

		match := indexExpressionPattern.FindStringSubmatch(expression)
		if match == nil {
			return nil, fmt.Errorf(
				"不支持的索引表达式 %q：只支持 列名 或 函数(列名)", expression)
		}

		funcName, column := match[1], match[2]
		if funcName == "" {
			column = match[3]
		} else {
			funcName = strings.ToLower(funcName)
			if !allowedIndexFunctions[funcName] {
				return nil, fmt.Errorf("不支持的索引函数 %q：可用 %s",
					funcName, strings.Join(sortedKeys(allowedIndexFunctions), ", "))
			}
		}

		if _, err := validateColumns([]any{column}, fieldNames, "index 表达式"); err != nil {
			return nil, err
		}
		if funcName == "" {
			result = append(result, column)
		} else {
			result = append(result, fmt.Sprintf("%s(%s)", funcName, column))
		}
	}
	return result, nil
}

// ── 部分索引条件 ─────────────────────────────────────────────────────

func normalizePartialWhere(expression string, columns []string) (string, error) {
	text := strings.TrimSpace(expression)
	if text == "" {
		return "", fmt.Errorf("index 的 where 必须是非空字符串")
	}

	for _, token := range whereForbidden {
		if strings.Contains(text, token) {
			return "", fmt.Errorf("index 的 where 不允许出现 %q：%q", token, expression)
		}
	}

	parts := whereJoinPattern.Split(text, -1)
	if len(parts)%2 == 0 {
		return "", fmt.Errorf("index 的 where 连接符使用有误：%q", expression)
	}

	rendered := make([]string, 0, len(parts))
	for position, part := range parts {
		if position%2 == 1 {
			if strings.EqualFold(part, "AND") {
				rendered = append(rendered, "AND")
			} else {
				rendered = append(rendered, "OR")
			}
			continue
		}
		term, err := normalizeWhereTerm(part, columns)
		if err != nil {
			return "", err
		}
		rendered = append(rendered, term)
	}
	return strings.Join(rendered, " "), nil
}

func normalizeWhereTerm(term string, columns []string) (string, error) {
	term = strings.TrimSpace(term)

	if match := whereTermNullPattern.FindStringSubmatch(term); match != nil {
		if err := requireWhereColumn(match[1], columns, term); err != nil {
			return "", err
		}
		if strings.TrimSpace(match[2]) != "" {
			return fmt.Sprintf("%s IS NOT NULL", match[1]), nil
		}
		return fmt.Sprintf("%s IS NULL", match[1]), nil
	}

	match := whereTermComparisonPattern.FindStringSubmatch(term)
	if match == nil {
		return "", fmt.Errorf(
			"不支持的 index.where 片段 %q：只支持“列 IS [NOT] NULL”或“列 比较符 字面量”，并用 AND / OR 连接",
			term)
	}

	column, operator, rawLiteral := match[1], match[2], match[3]
	if err := requireWhereColumn(column, columns, term); err != nil {
		return "", err
	}
	if operator == "!=" {
		operator = "<>"
	}

	literal, err := normalizeWhereLiteral(strings.TrimSpace(rawLiteral), term)
	if err != nil {
		return "", err
	}
	return fmt.Sprintf("%s %s %s", column, operator, literal), nil
}

func normalizeWhereLiteral(literal, term string) (string, error) {
	switch {
	case whereLiteralNumberPattern.MatchString(literal):
		return literal, nil
	case whereLiteralBoolPattern.MatchString(literal):
		return strings.ToUpper(literal), nil
	case whereLiteralStringPattern.MatchString(literal):
		return literal, nil
	default:
		return "", fmt.Errorf(
			"index.where 的字面量 %q 不被支持（只允许数字、'字符串'、true/false/null）：%q",
			literal, term)
	}
}

func requireWhereColumn(name string, columns []string, term string) error {
	if !containsString(columns, name) {
		return fmt.Errorf("index.where 引用了不在该索引 columns 里的列 %q：%q", name, term)
	}
	return nil
}

// ── 唯一约束 ─────────────────────────────────────────────────────────

func parseUniqueConstraints(
	raw []yamlUniqueConstraint, fieldNames map[string]struct{},
) ([]UniqueConstraint, error) {
	if len(raw) == 0 {
		return nil, nil
	}

	constraints := make([]UniqueConstraint, 0, len(raw))
	for _, entry := range raw {
		if len(entry.Columns) == 0 {
			return nil, fmt.Errorf("unique_constraint 必须提供非空的 columns 列表")
		}
		columns, err := validateColumns(entry.Columns, fieldNames, "unique_constraint")
		if err != nil {
			return nil, err
		}
		constraints = append(constraints, UniqueConstraint{Name: entry.Name, Columns: columns})
	}
	return constraints, nil
}

// ── 关系 ─────────────────────────────────────────────────────────────

func parseRelationships(
	raw []yamlRelationship,
	modelName string,
	fieldNames map[string]struct{},
	allModels []string,
) ([]Relationship, error) {
	if len(raw) == 0 {
		return nil, nil
	}

	relationships := make([]Relationship, 0, len(raw))
	seen := make(map[string]bool, len(raw))

	for _, entry := range raw {
		name := entry.Name
		if !IsValidIdentifier(name) {
			return nil, fmt.Errorf(
				"模型 %s 的 relationship 名 %q 不是合法的 Python 标识符", modelName, name)
		}
		if seen[name] {
			return nil, fmt.Errorf("模型 %s 的 relationship 名重复：%s", modelName, name)
		}
		if _, exists := fieldNames[name]; exists {
			return nil, fmt.Errorf(
				"模型 %s 的 relationship 名 %q 与字段名冲突", modelName, name)
		}
		seen[name] = true

		if !IsValidIdentifier(entry.Target) {
			return nil, fmt.Errorf(
				"模型 %s 的 relationship %s 缺少合法的 target", modelName, name)
		}
		if len(allModels) > 0 && !containsString(allModels, entry.Target) {
			return nil, fmt.Errorf(
				"模型 %s 的 relationship %s 指向不存在的模型 %q；可用模型：%s",
				modelName, name, entry.Target, strings.Join(allModels, ", "))
		}

		if entry.BackPopulates != "" && !IsValidIdentifier(entry.BackPopulates) {
			return nil, fmt.Errorf(
				"relationship %s.%s 的 back_populates 不是合法标识符", modelName, name)
		}

		if entry.Secondary != "" && !tableNamePattern.MatchString(entry.Secondary) {
			return nil, fmt.Errorf(
				"relationship %s.%s 的 secondary 表名非法：%q", modelName, name, entry.Secondary)
		}

		lazy := ""
		if entry.Lazy != "" {
			lazy = strings.ToLower(strings.TrimSpace(entry.Lazy))
			if !allowedLazy[lazy] {
				return nil, fmt.Errorf("relationship %s.%s 的 lazy 只支持 %s，收到 %q",
					modelName, name, strings.Join(sortedKeys(allowedLazy), ", "), entry.Lazy)
			}
		}

		cascade, err := parseCascade(entry.Cascade, modelName+"."+name)
		if err != nil {
			return nil, err
		}

		relationships = append(relationships, Relationship{
			Name:          name,
			Target:        entry.Target,
			BackPopulates: entry.BackPopulates,
			Cascade:       cascade,
			Lazy:          lazy,
			Uselist:       entry.Uselist,
			Secondary:     entry.Secondary,
		})
	}
	return relationships, nil
}

func parseCascade(raw, where string) (string, error) {
	if raw == "" {
		return "", nil
	}

	parts := strings.Split(raw, ",")
	normalized := make([]string, 0, len(parts))
	for _, part := range parts {
		value := strings.ToLower(strings.TrimSpace(part))
		if !allowedCascades[value] {
			return "", fmt.Errorf("relationship %s 的 cascade 含未知取值 %q；可用：%s",
				where, value, strings.Join(sortedKeys(allowedCascades), ", "))
		}
		normalized = append(normalized, value)
	}
	return strings.Join(normalized, ", "), nil
}

// validateBackPopulates 在所有模型解析完成后，交叉校验反向关系确实存在。
func validateBackPopulates(models []Model) error {
	byName := make(map[string]Model, len(models))
	for _, model := range models {
		byName[model.Name] = model
	}

	for _, model := range models {
		for _, relationship := range model.Relationships {
			if relationship.BackPopulates == "" {
				continue
			}
			target, ok := byName[relationship.Target]
			if !ok {
				continue
			}
			exists := false
			for _, candidate := range target.Relationships {
				if candidate.Name == relationship.BackPopulates {
					exists = true
					break
				}
			}
			if !exists {
				return fmt.Errorf(
					"模型 %s 的关系 %s 的 back_populates=%q 在模型 %s 上不存在",
					model.Name, relationship.Name, relationship.BackPopulates, target.Name)
			}
		}
	}
	return nil
}

func containsString(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}
