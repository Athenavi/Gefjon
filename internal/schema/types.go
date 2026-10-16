package schema

import (
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

// 类型所属模块。
const (
	ModuleSQLAlchemy = "sqlalchemy"
	ModulePostgreSQL = "sqlalchemy.dialects.postgresql"
	ModuleMySQL      = "sqlalchemy.dialects.mysql"
)

// GeneratedTypesModule 是 SQLAlchemy 未内置类型的辅助模块名。
const GeneratedTypesModule = "_gefjon_types"

// DefaultMaxLength 是无长度 String 的默认长度。
const DefaultMaxLength = 255

// TypeSpec 描述一个可用类型（目录由 tools/gen_go_typecatalog.py 生成）。
type TypeSpec struct {
	Name          string
	Module        string
	Dialect       string
	MinArgs       int
	MaxArgs       int
	TakesValues   bool
	TakesItemType bool
	TakesTimezone bool
	TakesDomain   bool
	TakesNotNull  bool
	Key           string
	ExtraArgs     []string
	Aliases       []string
	UDT           bool
}

// RegistryKey 是登记用的键（默认取 Name 的小写）。
func (s TypeSpec) RegistryKey() string {
	if s.Key != "" {
		return strings.ToLower(s.Key)
	}
	return strings.ToLower(s.Name)
}

var (
	typePrefixes = map[string]string{
		"sqlalchemy": ModuleSQLAlchemy,
		"sql":        ModuleSQLAlchemy,
		"postgresql": ModulePostgreSQL,
		"postgres":   ModulePostgreSQL,
		"pg":         ModulePostgreSQL,
		"mysql":      ModuleMySQL,
	}

	dialectModules = map[string]string{
		"postgresql": ModulePostgreSQL,
		"postgres":   ModulePostgreSQL,
		"pg":         ModulePostgreSQL,
		"mysql":      ModuleMySQL,
	}

	declarationPattern = regexp.MustCompile(
		`^(?:(?P<prefix>[A-Za-z_][A-Za-z0-9_]*)\.)?` +
			`(?P<name>[A-Za-z_][A-Za-z0-9_]*)` +
			`(?:\((?P<args>[^()]*)\))?$`)
	integerArgPattern = regexp.MustCompile(`^\d+$`)

	// byKey 把名字（登记键 + 别名）映射到候选类型；同名跨方言时会有多个候选。
	byKey map[string][]TypeSpec
)

func init() {
	byKey = make(map[string][]TypeSpec, len(typeCatalog)*2)
	for _, spec := range typeCatalog {
		byKey[spec.RegistryKey()] = append(byKey[spec.RegistryKey()], spec)
		for _, alias := range spec.Aliases {
			key := strings.ToLower(alias)
			byKey[key] = append(byKey[key], spec)
		}
	}
}

// TypeNames 返回全部可用名字（含别名），用于报错提示。
func TypeNames() []string {
	names := make([]string, 0, len(byKey))
	for name := range byKey {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

// resolveSpec 按名字与可选前缀挑出一个类型；同名跨方言时通用类型优先。
func resolveSpec(rawName, prefix, dialect string) (TypeSpec, error) {
	lowered := strings.ToLower(rawName)

	if prefix != "" {
		module, ok := typePrefixes[strings.ToLower(prefix)]
		if !ok {
			return TypeSpec{}, fmt.Errorf("未知的类型前缀 %q；可用前缀：sqlalchemy / pg / mysql", prefix)
		}
		for _, spec := range byKey[lowered] {
			if spec.Module == module {
				return spec, nil
			}
		}
		available := make([]string, 0, len(typeCatalog))
		for _, spec := range typeCatalog {
			if spec.Module == module {
				available = append(available, spec.Name)
			}
		}
		sort.Strings(available)
		return TypeSpec{}, fmt.Errorf(
			"模块 %s 下没有类型 %q；可用：%s", prefix, rawName, strings.Join(available, ", "))
	}

	candidates := byKey[lowered]
	if len(candidates) == 0 {
		return TypeSpec{}, fmt.Errorf(
			"不支持的类型 %q；可用类型：%s", rawName, strings.Join(TypeNames(), ", "))
	}
	if len(candidates) == 1 {
		return candidates[0], nil
	}

	// 同名跨方言：通用类型优先，其次按 database.dialect 挑选
	for _, spec := range candidates {
		if spec.Dialect == "" {
			return spec, nil
		}
	}
	if module, ok := dialectModules[strings.ToLower(dialect)]; ok {
		for _, spec := range candidates {
			if spec.Module == module {
				return spec, nil
			}
		}
	}

	dialects := make([]string, 0, len(candidates))
	for _, spec := range candidates {
		if spec.Dialect == "" {
			dialects = append(dialects, "generic")
		} else {
			dialects = append(dialects, spec.Dialect)
		}
	}
	sort.Strings(dialects)
	return TypeSpec{}, fmt.Errorf(
		"类型名 %q 在 %s 中含义不同：请写成 %s.%s，或在 models.yaml 里声明 database.dialect",
		rawName, strings.Join(dialects, " / "), candidates[0].Dialect, candidates[0].Name)
}

// parseTypeArgs 校验并返回位置参数。
func parseTypeArgs(rawArgs string, spec TypeSpec, declaration string) ([]string, error) {
	if strings.TrimSpace(rawArgs) == "" {
		return nil, nil
	}
	parts := strings.Split(rawArgs, ",")
	args := make([]string, 0, len(parts))
	for _, part := range parts {
		arg := strings.TrimSpace(part)
		if !integerArgPattern.MatchString(arg) {
			return nil, fmt.Errorf("类型 %q 的参数必须是整数，收到 %q", declaration, arg)
		}
		args = append(args, arg)
	}
	if len(args) < spec.MinArgs || len(args) > spec.MaxArgs {
		return nil, fmt.Errorf("类型 %s 需要 %d~%d 个参数，收到 %q",
			spec.Name, spec.MinArgs, spec.MaxArgs, declaration)
	}
	return args, nil
}

// TypeOptions 是解析类型声明时的附加参数。
type TypeOptions struct {
	MaxLength  int
	Dialect    string
	Values     []string
	ItemType   string
	Timezone   *bool
	DomainName string
	NotNull    *bool
}

func (o TypeOptions) maxLength() int {
	if o.MaxLength == 0 {
		return DefaultMaxLength
	}
	return o.MaxLength
}

// ParseType 把 YAML 里的类型声明解析成 IR 中的 ColumnType。
//
// 行为与 v0.1 的 gefjon.types.parse_type 对齐：白名单类型、纯数字参数、
// values / item_type / timezone / domain_name / not_null，以及同名跨方言的消歧规则。
func ParseType(declaration string, opts TypeOptions) (ColumnType, error) {
	text := strings.TrimSpace(declaration)
	if text == "" {
		return ColumnType{
			Expression: fmt.Sprintf("String(%d)", opts.maxLength()),
			ImportName: "String",
			Module:     ModuleSQLAlchemy,
		}, nil
	}

	match := declarationPattern.FindStringSubmatch(text)
	if match == nil {
		return ColumnType{}, fmt.Errorf(
			"无法解析字段类型 %q：只允许 [前缀.]类型名 或 类型名(数字[, 数字])", declaration)
	}
	prefix, name, rawArgs := match[1], match[2], match[3]

	spec, err := resolveSpec(name, prefix, opts.Dialect)
	if err != nil {
		return ColumnType{}, err
	}

	parts, err := parseTypeArgs(rawArgs, spec, text)
	if err != nil {
		return ColumnType{}, err
	}

	var components []ColumnType

	switch {
	case spec.TakesValues:
		if len(opts.Values) == 0 {
			return ColumnType{}, fmt.Errorf(
				"类型 %s 必须提供 values 列表，例如 values: [draft, published]", spec.Name)
		}
		parts = make([]string, 0, len(opts.Values))
		for _, value := range opts.Values {
			parts = append(parts, PyRepr(value))
		}
	case len(opts.Values) > 0:
		return ColumnType{}, fmt.Errorf("类型 %s 不接受 values", spec.Name)
	}

	if spec.TakesItemType {
		if opts.ItemType == "" {
			return ColumnType{}, fmt.Errorf(
				"类型 %s 必须提供 item_type，例如 item_type: Text", spec.Name)
		}
		inner, err := ParseType(opts.ItemType, TypeOptions{
			MaxLength: opts.MaxLength,
			Dialect:   opts.Dialect,
		})
		if err != nil {
			return ColumnType{}, err
		}
		if inner.Dialect != "" && inner.Dialect != spec.Dialect {
			return ColumnType{}, fmt.Errorf(
				"元素类型不能是 %s 专有类型：%q", inner.Dialect, opts.ItemType)
		}
		parts = []string{inner.Expression}
		components = []ColumnType{inner}
	} else if opts.ItemType != "" {
		return ColumnType{}, fmt.Errorf("类型 %s 不接受 item_type", spec.Name)
	}

	if spec.TakesDomain {
		if opts.DomainName == "" {
			return ColumnType{}, fmt.Errorf(
				"类型 %s 必须提供 domain_name，例如 domain_name: us_postal_code", spec.Name)
		}
		if len(parts) != 1 {
			return ColumnType{}, fmt.Errorf("类型 %s 需要 item_type 作为基类型", spec.Name)
		}
		parts = []string{PyRepr(opts.DomainName), parts[0]}
		if opts.NotNull != nil && *opts.NotNull {
			parts = append(parts, "not_null=True")
		}
	} else if opts.DomainName != "" {
		return ColumnType{}, fmt.Errorf("类型 %s 不接受 domain_name", spec.Name)
	} else if opts.NotNull != nil {
		return ColumnType{}, fmt.Errorf("类型 %s 不接受 not_null", spec.Name)
	}

	if opts.Timezone != nil {
		if !spec.TakesTimezone {
			return ColumnType{}, fmt.Errorf("类型 %s 不接受 timezone 选项", spec.Name)
		}
		if *opts.Timezone {
			parts = append(parts, "timezone=True")
		}
	}

	parts = append(parts, spec.ExtraArgs...)

	if spec.Name == "String" && len(parts) == 0 {
		parts = []string{strconv.Itoa(opts.maxLength())}
	}

	expression := spec.Name
	if len(parts) > 0 {
		expression = fmt.Sprintf("%s(%s)", spec.Name, strings.Join(parts, ", "))
	}

	return ColumnType{
		Expression: expression,
		ImportName: spec.Name,
		Module:     spec.Module,
		Dialect:    spec.Dialect,
		Components: components,
		Generated:  spec.UDT,
	}, nil
}

// ImportPairs 返回该类型需要的 (模块, 类型名) 列表，含嵌套类型。
//
// 与 v0.1 一致：需要生成额外类型时，模块换成辅助模块名。
func (t ColumnType) ImportPairs() [][2]string {
	module := t.Module
	if t.Generated {
		module = GeneratedTypesModule
	}
	pairs := [][2]string{{module, t.ImportName}}
	for _, component := range t.Components {
		pairs = append(pairs, component.ImportPairs()...)
	}
	return pairs
}

// GeneratedNames 返回需要在辅助模块里生成的类型名（含嵌套）。
func (t ColumnType) GeneratedNames() []string {
	var names []string
	if t.Generated {
		names = append(names, t.ImportName)
	}
	for _, component := range t.Components {
		names = append(names, component.GeneratedNames()...)
	}
	return names
}
