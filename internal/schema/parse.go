package schema

import (
	"fmt"
	"os"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"gopkg.in/yaml.v3"
)

// DefaultMigrationsDir 是迁移目录的默认名。
const DefaultMigrationsDir = "migrations"

// DefaultOutputDir 是模型包输出目录的默认名。
const DefaultOutputDir = "models"

// 校验用正则，与 v0.1 的 config.py 保持一致。
var (
	tableNamePattern  = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_.]*$`)
	foreignKeyPattern = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$`)
	domainNamePattern = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$`)
)

// ── YAML 侧结构（校验前的原始形状）──────────────────────────────────

type yamlDocument struct {
	Version   string         `yaml:"version"`
	Project   *yamlProject   `yaml:"project"`
	Database  *yamlDatabase  `yaml:"database"`
	Migration *yamlMigration `yaml:"migration"`
	Models    []yamlModel    `yaml:"models"`
	Targets   []yamlTarget   `yaml:"targets"`
	Mapping   *yamlMapping   `yaml:"mapping"`
}

type yamlProject struct {
	Name    string `yaml:"name"`
	Version string `yaml:"version"`
}

type yamlDatabase struct {
	URL      string `yaml:"url"`
	Dialect  string `yaml:"dialect"`
	PoolSize *int   `yaml:"pool_size"`
	Echo     bool   `yaml:"echo"`
}

type yamlMigration struct {
	Directory string `yaml:"directory"`
	Template  string `yaml:"template"`
}

type yamlTarget struct {
	Name string `yaml:"name"`
	Kind string `yaml:"kind"`
	Dir  string `yaml:"dir"`
}

type yamlMapping struct {
	ThirdParty []yamlThirdParty `yaml:"third_party"`
}

type yamlThirdParty struct {
	Project    string `yaml:"project"`
	Version    string `yaml:"version"`
	DBRevision string `yaml:"db_revision"`
}

type yamlModel struct {
	Name              string                 `yaml:"name"`
	Table             string                 `yaml:"table"`
	Description       string                 `yaml:"description"`
	Module            string                 `yaml:"module"`
	Unlogged          *bool                  `yaml:"unlogged"`
	Fields            []yamlField            `yaml:"fields"`
	Indexes           []yamlIndex            `yaml:"indexes"`
	UniqueConstraints []yamlUniqueConstraint `yaml:"unique_constraints"`
	Relationships     []yamlRelationship     `yaml:"relationships"`
}

type yamlField struct {
	Name            string `yaml:"name"`
	Type            string `yaml:"type"`
	Column          string `yaml:"column"`
	MaxLength       *int   `yaml:"maxLength"`
	MaxLengthLegacy *int   `yaml:"max_length"`
	Nullable        bool   `yaml:"nullable"`
	PrimaryKey      bool   `yaml:"primary_key"`
	Autoincrement   *bool  `yaml:"autoincrement"`
	Unique          bool   `yaml:"unique"`
	Index           bool   `yaml:"index"`
	Default         any    `yaml:"default"`
	Description     string `yaml:"description"`
	Doc             string `yaml:"doc"`
	ForeignKey      string `yaml:"foreign_key"`
	Values          []any  `yaml:"values"`
	ItemType        string `yaml:"item_type"`
	Timezone        *bool  `yaml:"timezone"`
	DomainName      string `yaml:"domain_name"`
	NotNull         *bool  `yaml:"not_null"`
}

type yamlIndex struct {
	Columns      []any           `yaml:"columns"`
	Name         string          `yaml:"name"`
	Unique       bool            `yaml:"unique"`
	Using        string          `yaml:"using"`
	Ops          Ordered[string] `yaml:"ops"`
	Where        string          `yaml:"where"`
	Expressions  []any           `yaml:"expressions"`
	Concurrently *bool           `yaml:"concurrently"`
	Prefix       string          `yaml:"prefix"`
	Lengths      Ordered[int]    `yaml:"lengths"`
}

type yamlUniqueConstraint struct {
	Name    string `yaml:"name"`
	Columns []any  `yaml:"columns"`
}

type yamlRelationship struct {
	Name          string `yaml:"name"`
	Target        string `yaml:"target"`
	BackPopulates string `yaml:"back_populates"`
	Cascade       string `yaml:"cascade"`
	Lazy          string `yaml:"lazy"`
	Uselist       *bool  `yaml:"uselist"`
	Secondary     string `yaml:"secondary"`
}

// ── 加载 ─────────────────────────────────────────────────────────────

// Load 读取并校验 models.yaml，返回与后端无关的 IR。
func Load(path string) (*Document, error) {
	source, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, fmt.Errorf("找不到配置文件：%s", path)
		}
		return nil, fmt.Errorf("无法读取配置文件 %s：%v", path, err)
	}

	var raw yamlDocument
	if err := yaml.Unmarshal(source, &raw); err != nil {
		return nil, fmt.Errorf("配置文件 %s 不是合法 YAML：%v", path, err)
	}

	database, err := parseDatabase(&raw)
	if err != nil {
		return nil, err
	}

	models, err := parseModels(raw.Models, database.Dialect)
	if err != nil {
		return nil, err
	}

	targets, err := parseTargets(&raw)
	if err != nil {
		return nil, err
	}

	mapping, err := parseMapping(&raw)
	if err != nil {
		return nil, err
	}

	return &Document{
		SourcePath:      path,
		Project:         parseProject(&raw),
		Database:        database,
		Migration:       parseMigration(&raw),
		Models:          models,
		Targets:         targets,
		Mapping:         Mapping{ThirdParty: mapping},
		TopLevelVersion: raw.Version,
	}, nil
}

func parseProject(raw *yamlDocument) Project {
	project := Project{Name: "gefjon-project", Version: "0.0.0"}
	if raw.Project != nil {
		if raw.Project.Name != "" {
			project.Name = raw.Project.Name
		}
		if raw.Project.Version != "" {
			project.Version = raw.Project.Version
		} else if raw.Version != "" {
			project.Version = raw.Version
		}
	} else if raw.Version != "" {
		project.Version = raw.Version
	}
	return project
}

func parseDatabase(raw *yamlDocument) (Database, error) {
	if raw.Database == nil {
		return Database{}, nil
	}
	if raw.Database.PoolSize != nil && *raw.Database.PoolSize <= 0 {
		return Database{}, fmt.Errorf("database.pool_size 必须是正整数")
	}

	database := Database{
		URL:     raw.Database.URL,
		Dialect: raw.Database.Dialect,
		Echo:    raw.Database.Echo,
	}
	if raw.Database.PoolSize != nil {
		database.PoolSize = *raw.Database.PoolSize
	}
	return database, nil
}

func parseMigration(raw *yamlDocument) Migration {
	migration := Migration{Directory: DefaultMigrationsDir}
	if raw.Migration != nil {
		if raw.Migration.Directory != "" {
			migration.Directory = raw.Migration.Directory
		}
		migration.Template = raw.Migration.Template
	}
	return migration
}

// parseTargets 解析 v0.2 的 targets 段；为空时由调用方按 v0.1 行为推断后端。
func parseTargets(raw *yamlDocument) ([]Target, error) {
	if len(raw.Targets) == 0 {
		return nil, nil
	}

	targets := make([]Target, 0, len(raw.Targets))
	for index, item := range raw.Targets {
		kind := strings.TrimSpace(item.Kind)
		if kind == "" {
			return nil, fmt.Errorf("targets[%d] 缺少 kind（alembic / atlas / flyway / plain-sql）", index)
		}
		name := strings.TrimSpace(item.Name)
		if name == "" {
			name = kind
		}
		targets = append(targets, Target{Name: name, Kind: kind, Dir: item.Dir})
	}
	return targets, nil
}

func parseMapping(raw *yamlDocument) ([]ThirdPartyMapping, error) {
	if raw.Mapping == nil {
		return nil, nil
	}

	mappings := make([]ThirdPartyMapping, 0, len(raw.Mapping.ThirdParty))
	for _, entry := range raw.Mapping.ThirdParty {
		var missing []string
		if entry.Project == "" {
			missing = append(missing, "project")
		}
		if entry.Version == "" {
			missing = append(missing, "version")
		}
		if entry.DBRevision == "" {
			missing = append(missing, "db_revision")
		}
		if len(missing) > 0 {
			return nil, fmt.Errorf("mapping.third_party 条目缺少字段：%s", strings.Join(missing, ", "))
		}
		mappings = append(mappings, ThirdPartyMapping{
			Project:    entry.Project,
			Version:    entry.Version,
			DBRevision: entry.DBRevision,
		})
	}
	return mappings, nil
}

// ── 模型 ─────────────────────────────────────────────────────────────

func parseModels(raw []yamlModel, dialect string) ([]Model, error) {
	if len(raw) == 0 {
		return nil, nil
	}

	// 第一遍：先收集全部模型名，使 relationships 的 target 可以引用任意模型
	names := make([]string, 0, len(raw))
	for _, entry := range raw {
		if !IsValidIdentifier(entry.Name) {
			return nil, fmt.Errorf("模型名 %q 不是合法的 Python 类名", entry.Name)
		}
		names = append(names, entry.Name)
	}

	models := make([]Model, 0, len(raw))
	seenNames := make(map[string]bool, len(raw))
	seenTables := make(map[string]bool, len(raw))

	for _, entry := range raw {
		model, err := parseModel(entry, names, dialect)
		if err != nil {
			return nil, err
		}
		if seenNames[model.Name] {
			return nil, fmt.Errorf("模型名重复：%s", model.Name)
		}
		if seenTables[model.Table] {
			return nil, fmt.Errorf("表名重复：%s", model.Table)
		}
		seenNames[model.Name] = true
		seenTables[model.Table] = true
		models = append(models, model)
	}

	if err := validateBackPopulates(models); err != nil {
		return nil, err
	}
	return models, nil
}

func parseModel(entry yamlModel, allModels []string, dialect string) (Model, error) {
	table := ToTableName(entry.Name, entry.Table)
	if !tableNamePattern.MatchString(table) {
		return Model{}, fmt.Errorf("表名 %q 非法：只允许字母、数字、下划线和点", table)
	}

	module := strings.Trim(strings.ReplaceAll(strings.TrimSpace(entry.Module), "\\", "/"), "/")

	unlogged := false
	if entry.Unlogged != nil {
		unlogged = *entry.Unlogged
	}

	fields, err := parseFields(entry.Fields, entry.Name, dialect)
	if err != nil {
		return Model{}, err
	}

	fieldNames := make(map[string]struct{}, len(fields))
	for _, field := range fields {
		fieldNames[field.Name] = struct{}{}
	}

	indexes, err := parseIndexes(entry.Indexes, table, fieldNames)
	if err != nil {
		return Model{}, err
	}

	constraints, err := parseUniqueConstraints(entry.UniqueConstraints, fieldNames)
	if err != nil {
		return Model{}, err
	}

	relationships, err := parseRelationships(
		entry.Relationships, entry.Name, fieldNames, allModels)
	if err != nil {
		return Model{}, err
	}

	description := entry.Description
	if description == "" {
		description = entry.Name
	}

	return Model{
		Name:              entry.Name,
		Table:             table,
		Description:       description,
		Module:            module,
		Unlogged:          unlogged,
		Fields:            fields,
		Indexes:           indexes,
		UniqueConstraints: constraints,
		Relationships:     relationships,
	}, nil
}

// ── 字段 ─────────────────────────────────────────────────────────────

func parseFields(raw []yamlField, modelName, dialect string) ([]Field, error) {
	if len(raw) == 0 {
		return nil, fmt.Errorf("模型 %s 必须提供非空的 fields 列表", modelName)
	}

	fields := make([]Field, 0, len(raw))
	seenAttributes := make(map[string]bool, len(raw))
	seenColumns := make(map[string]bool, len(raw))

	for _, entry := range raw {
		field, err := parseField(entry, modelName, dialect)
		if err != nil {
			return nil, err
		}
		if seenAttributes[field.Name] {
			return nil, fmt.Errorf("模型 %s 的字段名重复：%s", modelName, field.Name)
		}
		if seenColumns[field.Column] {
			return nil, fmt.Errorf("模型 %s 的列名重复：%s", modelName, field.Column)
		}
		seenAttributes[field.Name] = true
		seenColumns[field.Column] = true
		fields = append(fields, field)
	}
	return fields, nil
}

func parseField(entry yamlField, modelName, dialect string) (Field, error) {
	rawName := entry.Name
	if rawName == "" {
		return Field{}, fmt.Errorf("模型 %s 存在缺少 name 的字段", modelName)
	}
	if !IsValidIdentifier(rawName) {
		return Field{}, fmt.Errorf(
			"模型 %s 的字段名 %q 不是合法的 Python 标识符", modelName, rawName)
	}

	name, column, columnExplicit := rawName, rawName, false
	switch {
	case entry.Column != "":
		name, column, columnExplicit = rawName, entry.Column, true
	case isReserved(rawName):
		name, column, columnExplicit = "extra_"+rawName, rawName, true
	}

	if entry.MaxLength != nil && *entry.MaxLength <= 0 {
		return Field{}, fmt.Errorf("字段 %s 的 maxLength 必须是正整数", rawName)
	}
	maxLength := 0
	if entry.MaxLength != nil {
		maxLength = *entry.MaxLength
	} else if entry.MaxLengthLegacy != nil {
		if *entry.MaxLengthLegacy <= 0 {
			return Field{}, fmt.Errorf("字段 %s 的 maxLength 必须是正整数", rawName)
		}
		maxLength = *entry.MaxLengthLegacy
	}

	values, err := parseFieldValues(entry.Values, rawName)
	if err != nil {
		return Field{}, err
	}

	columnType, err := ParseType(entry.Type, TypeOptions{
		MaxLength:  maxLength,
		Dialect:    dialect,
		Values:     values,
		ItemType:   entry.ItemType,
		Timezone:   entry.Timezone,
		DomainName: entry.DomainName,
		NotNull:    entry.NotNull,
	})
	if err != nil {
		return Field{}, err
	}

	if entry.DomainName != "" && !domainNamePattern.MatchString(entry.DomainName) {
		return Field{}, fmt.Errorf(
			"字段 %s 的 domain_name 非法（只允许标识符，可带模式前缀）", rawName)
	}

	primaryKey := entry.PrimaryKey
	nullable := entry.Nullable
	if primaryKey {
		nullable = false
	}

	autoincrement := primaryKey && isIntegerType(columnType.ImportName)
	if entry.Autoincrement != nil {
		autoincrement = *entry.Autoincrement
	}

	defaultSQL, defaultImport, err := parseDefault(entry, rawName)
	if err != nil {
		return Field{}, err
	}

	if entry.ForeignKey != "" && !foreignKeyPattern.MatchString(entry.ForeignKey) {
		return Field{}, fmt.Errorf(
			"字段 %s 的 foreign_key 必须形如 表名.列名，收到 %q", rawName, entry.ForeignKey)
	}

	doc := entry.Description
	if doc == "" {
		doc = entry.Doc
	}
	if doc == "" {
		doc = rawName
	}

	return Field{
		Name:           name,
		Column:         column,
		ColumnExplicit: columnExplicit,
		Type:           columnType,
		Nullable:       nullable,
		PrimaryKey:     primaryKey,
		Autoincrement:  autoincrement,
		Unique:         entry.Unique,
		Index:          entry.Index,
		DefaultSQL:     defaultSQL,
		DefaultImport:  defaultImport,
		Doc:            doc,
		ForeignKey:     entry.ForeignKey,
	}, nil
}

func isIntegerType(importName string) bool {
	switch importName {
	case "Integer", "BigInteger", "SmallInteger":
		return true
	default:
		return false
	}
}

func parseFieldValues(raw []any, fieldName string) ([]string, error) {
	if raw == nil {
		return nil, nil
	}
	if len(raw) == 0 {
		return nil, fmt.Errorf("字段 %s 的 values 必须是非空列表", fieldName)
	}

	values := make([]string, 0, len(raw))
	for _, item := range raw {
		switch item.(type) {
		case string, bool, int, float64:
			values = append(values, pyStr(item))
		default:
			return nil, fmt.Errorf("字段 %s 的 values 只能是字符串或数字", fieldName)
		}
	}
	return values, nil
}

// ── 默认值 ───────────────────────────────────────────────────────────

var (
	sqlFuncCallPattern  = regexp.MustCompile(`^func\.([A-Za-z_][A-Za-z0-9_]*)\(\)$`)
	looksLikeExpression = regexp.MustCompile(`[().]`)
)

var allowedSQLFuncs = map[string]bool{
	"now": true, "current_timestamp": true, "current_date": true,
	"current_time": true, "random": true, "uuid_generate_v4": true,
	"gen_random_uuid": true,
}

type callableDefault struct {
	expression string
	importLine string
}

var allowedCallables = map[string]callableDefault{
	"datetime.utcnow": {"datetime.utcnow", "from datetime import datetime"},
	"datetime.now":    {"datetime.now()", "from datetime import datetime"},
	"uuid.uuid4":      {"uuid.uuid4", "import uuid"},
}

// parseDefault 把 default 解析成安全的源码片段。
//
// 只有白名单内的形式会被当作表达式，其余字符串按字符串字面量处理；
// 看起来像表达式但不在白名单内的输入直接报错，而不是静默变成字符串。
func parseDefault(entry yamlField, fieldName string) (string, string, error) {
	// nil 既表示未提供，也表示显式 default: null —— 与 v0.1 行为一致
	if entry.Default == nil {
		return "", "", nil
	}

	switch typed := entry.Default.(type) {
	case bool:
		return pyReprBool(typed), "", nil
	case int:
		return strconv.Itoa(typed), "", nil
	case float64:
		return pyStr(typed), "", nil
	}

	text, ok := entry.Default.(string)
	if !ok {
		return "", "", fmt.Errorf("字段 %s 的 default 类型不受支持：%v", fieldName, entry.Default)
	}

	text = strings.TrimSpace(text)
	if text == "" {
		return "''", "", nil
	}

	if match := sqlFuncCallPattern.FindStringSubmatch(text); match != nil {
		funcName := match[1]
		if !allowedSQLFuncs[funcName] {
			return "", "", fmt.Errorf(
				"字段 %s 的 default 使用了不支持的函数 func.%s()；可用：%s",
				fieldName, funcName, strings.Join(sortedKeys(allowedSQLFuncs), ", "))
		}
		return text, "from sqlalchemy.sql import func", nil
	}

	if callable, ok := allowedCallables[strings.TrimRight(text, "()")]; ok {
		return callable.expression, callable.importLine, nil
	}

	if looksLikeExpression.MatchString(text) {
		return "", "", fmt.Errorf(
			"字段 %s 的 default=%q 看起来是表达式，但不在允许的白名单内。"+
				"若要作为字符串字面量，请写成引用形式（例如 default: \"'%s'\"）",
			fieldName, text, text)
	}

	return PyRepr(text), "", nil
}

// ── 小工具 ───────────────────────────────────────────────────────────

func isReserved(name string) bool {
	_, ok := ReservedNames[name]
	return ok
}

// pyStr 复刻 Python 的 str()，用于 values（v0.1 用 str(value) 归一）。
func pyStr(value any) string {
	switch typed := value.(type) {
	case string:
		return typed
	case bool:
		return pyReprBool(typed)
	case int:
		return strconv.Itoa(typed)
	case float64:
		return strconv.FormatFloat(typed, 'g', -1, 64)
	default:
		return fmt.Sprintf("%v", typed)
	}
}

// pyReprBool 复刻 Python 的 repr(bool)：True / False（首字母大写）。
func pyReprBool(value bool) string {
	if value {
		return "True"
	}
	return "False"
}

func sortedKeys[V any](m map[string]V) []string {
	keys := make([]string, 0, len(m))
	for key := range m {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}

func sortedFieldNames(fieldNames map[string]struct{}) string {
	names := make([]string, 0, len(fieldNames))
	for name := range fieldNames {
		names = append(names, name)
	}
	sort.Strings(names)
	return strings.Join(names, ", ")
}

func slugify(expressions []string) string {
	parts := make([]string, 0, len(expressions))
	for _, expression := range expressions {
		cleaned := strings.Trim(regexp.MustCompile(`[^0-9a-z]+`).ReplaceAllString(
			strings.ToLower(expression), "_"), "_")
		if cleaned != "" {
			parts = append(parts, cleaned)
		}
	}
	if len(parts) == 0 {
		return "expr"
	}
	return strings.Join(parts, "_")
}
