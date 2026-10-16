// Package render 把 IR 渲染成目标产物。
//
// 渲染刻意用字符串拼装，而不是 text/template：产物必须与 v0.1 **逐字节一致**，
// 而模板引擎的空白控制差异极难对齐。这里的格式是照着 golden fixtures 反推的
// （tests/golden/*/models/**），并由 render_test.go 逐字节校验。
package render

import (
	"fmt"
	"sort"
	"strings"

	"github.com/Athenavi/Gefjon/internal/schema"
)

// BaseModule 是所有模型共享的声明式基类。
const BaseModule = `"""所有模型的声明式基类 —— 由 Gefjon 生成，请勿手动修改。"""

from sqlalchemy.orm import declarative_base

Base = declarative_base()
`

// PackageFiles 返回「相对模型包根的路径 -> 文件内容」。
//
// 与 v0.1 的 render_package 对应：先全部渲染到内存，再由调用方决定落盘还是比对。
func PackageFiles(models []schema.Model) map[string]string {
	files := map[string]string{
		"base.py":     BaseModule,
		"__init__.py": PackageInit(models),
	}

	for _, model := range models {
		files[modelPath(model)] = ModelFile(model)
	}

	if names := collectGeneratedNames(models); len(names) > 0 {
		files[schema.GeneratedTypesModule+".py"] = GeneratedTypes(names)
	}

	for _, module := range collectModules(models) {
		files[module+"/__init__.py"] = SubpackageInit(module, filterByModule(models, module))
	}
	return files
}

// ModelFile 渲染单个模型文件。
func ModelFile(model schema.Model) string {
	var builder strings.Builder

	fmt.Fprintf(&builder, `"""%s 模型 —— 由 Gefjon 生成，请勿手动修改。

模型：%s
表名：%s
"""
`, model.Description, model.Name, model.Table)

	for _, line := range importLines(model) {
		builder.WriteString(line)
		builder.WriteByte('\n')
	}
	builder.WriteString("\n\n")

	fmt.Fprintf(&builder, "class %s(Base):\n", model.Name)
	fmt.Fprintf(&builder, "    \"\"\"%s\"\"\"\n", model.Description)
	fmt.Fprintf(&builder, "\n    __tablename__ = %s\n", schema.PyRepr(model.Table))

	if args := tableArgs(model); len(args) > 0 {
		builder.WriteString("    __table_args__ = (\n")
		for _, item := range args {
			fmt.Fprintf(&builder, "        %s,\n", item)
		}
		builder.WriteString("    )\n")
	}

	builder.WriteString("\n")
	for _, field := range model.Fields {
		fmt.Fprintf(&builder, "    %s\n", renderColumn(field))
	}

	if len(model.Relationships) > 0 {
		builder.WriteString("\n")
		for _, relationship := range model.Relationships {
			fmt.Fprintf(&builder, "    %s\n", renderRelationship(relationship))
		}
	}

	builder.WriteString(`
    def to_dict(self):
        """返回 {列名: 值} 的字典。"""
        return {
            attribute.key: getattr(self, attribute.key)
            for attribute in self.__mapper__.column_attrs
        }

    def __repr__(self):
        primary_key = self.__mapper__.primary_key
        values = ", ".join(
            f"{column.key}={getattr(self, column.key)!r}" for column in primary_key
        )
`)
	fmt.Fprintf(&builder, "        return f\"<%s {values}>\"\n", model.Name)

	if model.Unlogged {
		fmt.Fprintf(&builder, `
# PostgreSQL UNLOGGED 表：SQLAlchemy 没有对应参数，建表后立刻改属性
@event.listens_for(%s.__table__, "after_create")
def _gefjon_set_unlogged_%s(target, connection, **kw):
    connection.execute(text(f"ALTER TABLE {target.name} SET UNLOGGED"))
`, model.Name, strings.ToLower(model.Name))
	}

	return builder.String()
}

// PackageInit 渲染模型包顶层的 __init__.py。
func PackageInit(models []schema.Model) string {
	lines := []string{
		`"""模型包 —— 由 Gefjon 生成，请勿手动修改。"""`,
		"",
		"from .base import Base",
	}

	sorted := make([]schema.Model, len(models))
	copy(sorted, models)
	sort.Slice(sorted, func(i, j int) bool {
		if sorted[i].Module != sorted[j].Module {
			return sorted[i].Module < sorted[j].Module
		}
		return sorted[i].Name < sorted[j].Name
	})

	for _, model := range sorted {
		reference := "."
		if model.Module != "" {
			reference = "." + strings.ReplaceAll(model.Module, "/", ".") + "."
		}
		lines = append(lines, fmt.Sprintf("from %s%s import %s",
			reference, schema.ToModuleName(model.Name), model.Name))
	}

	lines = append(lines, "")
	lines = append(lines, fmt.Sprintf("__all__ = [%s]", quotedSorted(exportedNames(models))))
	return strings.Join(lines, "\n") + "\n"
}

// SubpackageInit 渲染子包的 __init__.py。
//
// 必须用**同层**的相对导入（from .x import X）：子包 __init__.py 与模型文件同目录。
// v0.1 曾误用模型文件的深度公式，生成 from ..x import X，导致整个包无法 import。
func SubpackageInit(module string, models []schema.Model) string {
	lines := []string{
		fmt.Sprintf(`"""%s 子包 —— 由 Gefjon 生成，请勿手动修改。"""`, module),
		"",
	}

	sorted := make([]schema.Model, len(models))
	copy(sorted, models)
	sort.Slice(sorted, func(i, j int) bool { return sorted[i].Name < sorted[j].Name })

	names := make([]string, 0, len(sorted))
	for _, model := range sorted {
		lines = append(lines, fmt.Sprintf("from .%s import %s",
			schema.ToModuleName(model.Name), model.Name))
		names = append(names, model.Name)
	}

	lines = append(lines, "")
	lines = append(lines, fmt.Sprintf("__all__ = [%s]", quotedSorted(names)))
	return strings.Join(lines, "\n") + "\n"
}

// GeneratedTypes 渲染 SQLAlchemy 未内置类型所需的辅助模块。
func GeneratedTypes(names []string) string {
	var builder strings.Builder
	builder.WriteString(`"""SQLAlchemy 未内置的方言类型 —— 由 Gefjon 生成，请勿手动修改。

这些类型只负责把类型名渲染成 SQL（` + "``get_col_spec``" + `），具体语义由数据库决定。
"""

from sqlalchemy.types import UserDefinedType


class _GefjonNamedType(UserDefinedType):
    """按名字渲染 SQL 类型的基类。"""

    sql_name = ""

    def get_col_spec(self, **kw):
        return self.sql_name

    def __repr__(self):
        return f"{type(self).__name__}()"
`)

	sorted := append([]string(nil), names...)
	sort.Strings(sorted)
	for _, name := range sorted {
		fmt.Fprintf(&builder, `

class %s(_GefjonNamedType):
    sql_name = "%s"
`, name, name)
	}
	return builder.String()
}

// ── 片段渲染 ─────────────────────────────────────────────────────────

func renderColumn(field schema.Field) string {
	parts := make([]string, 0, 8)
	if field.ColumnExplicit {
		parts = append(parts, schema.PyRepr(field.Column))
	}
	parts = append(parts, field.Type.Expression)

	if field.ForeignKey != "" {
		parts = append(parts, fmt.Sprintf("ForeignKey(%s)", schema.PyRepr(field.ForeignKey)))
	}

	if field.PrimaryKey {
		parts = append(parts, "primary_key=True")
		if field.Autoincrement {
			parts = append(parts, "autoincrement=True")
		}
	} else {
		parts = append(parts, fmt.Sprintf("nullable=%s", pyBool(field.Nullable)))
	}

	if field.Unique {
		parts = append(parts, "unique=True")
	}
	if field.Index && !field.Unique && !field.PrimaryKey {
		parts = append(parts, "index=True")
	}
	if field.DefaultSQL != "" {
		parts = append(parts, fmt.Sprintf("default=%s", field.DefaultSQL))
	}
	parts = append(parts, fmt.Sprintf("doc=%s", schema.PyRepr(field.Doc)))

	return fmt.Sprintf("%s = Column(%s)", field.Name, strings.Join(parts, ", "))
}

func renderRelationship(relationship schema.Relationship) string {
	parts := []string{schema.PyRepr(relationship.Target)}
	if relationship.Secondary != "" {
		parts = append(parts, fmt.Sprintf("secondary=%s", schema.PyRepr(relationship.Secondary)))
	}
	if relationship.BackPopulates != "" {
		parts = append(parts, fmt.Sprintf("back_populates=%s", schema.PyRepr(relationship.BackPopulates)))
	}
	if relationship.Cascade != "" {
		parts = append(parts, fmt.Sprintf("cascade=%s", schema.PyRepr(relationship.Cascade)))
	}
	if relationship.Lazy != "" {
		parts = append(parts, fmt.Sprintf("lazy=%s", schema.PyRepr(relationship.Lazy)))
	}
	if relationship.Uselist != nil {
		parts = append(parts, fmt.Sprintf("uselist=%s", pyBool(*relationship.Uselist)))
	}
	return fmt.Sprintf("%s = relationship(%s)", relationship.Name, strings.Join(parts, ", "))
}

func tableArgs(model schema.Model) []string {
	items := make([]string, 0, len(model.UniqueConstraints)+len(model.Indexes))

	for _, constraint := range model.UniqueConstraints {
		columns := strings.Join(quotedList(constraint.Columns), ", ")
		if constraint.Name != "" {
			items = append(items, fmt.Sprintf("UniqueConstraint(%s, name=%s)",
				columns, schema.PyRepr(constraint.Name)))
		} else {
			items = append(items, fmt.Sprintf("UniqueConstraint(%s)", columns))
		}
	}
	for _, index := range model.Indexes {
		items = append(items, renderIndex(index))
	}
	return items
}

func renderIndex(index schema.Index) string {
	parts := []string{schema.PyRepr(index.Name)}
	parts = append(parts, quotedList(index.Columns)...)

	for _, expression := range index.Expressions {
		parts = append(parts, fmt.Sprintf("text(%s)", schema.PyRepr(expression)))
	}
	if index.Unique {
		parts = append(parts, "unique=True")
	}
	if index.Using != "" {
		parts = append(parts, fmt.Sprintf("postgresql_using=%s", schema.PyRepr(index.Using)))
	}
	if len(index.Ops) > 0 {
		entries := make([]string, 0, len(index.Ops))
		for _, entry := range index.Ops {
			entries = append(entries, fmt.Sprintf("%s: %s",
				schema.PyRepr(entry.Key), schema.PyRepr(entry.Value)))
		}
		parts = append(parts, fmt.Sprintf("postgresql_ops={%s}", strings.Join(entries, ", ")))
	}
	if index.WhereSQL != "" {
		parts = append(parts, fmt.Sprintf("postgresql_where=text(%s)", schema.PyRepr(index.WhereSQL)))
	}
	if index.Concurrently {
		parts = append(parts, "postgresql_concurrently=True")
	}
	if index.Prefix != "" {
		parts = append(parts, fmt.Sprintf("mysql_prefix=%s", schema.PyRepr(strings.ToUpper(index.Prefix))))
	}
	if len(index.Lengths) > 0 {
		entries := make([]string, 0, len(index.Lengths))
		for _, entry := range index.Lengths {
			entries = append(entries, fmt.Sprintf("%s: %d", schema.PyRepr(entry.Key), entry.Value))
		}
		parts = append(parts, fmt.Sprintf("mysql_length={%s}", strings.Join(entries, ", ")))
	}
	return fmt.Sprintf("Index(%s)", strings.Join(parts, ", "))
}

func importLines(model schema.Model) []string {
	byModule := map[string]map[string]bool{schema.ModuleSQLAlchemy: {"Column": true}}
	generated := map[string]bool{}

	addModule := func(module, name string) {
		if byModule[module] == nil {
			byModule[module] = map[string]bool{}
		}
		byModule[module][name] = true
	}

	for _, field := range model.Fields {
		for _, pair := range field.Type.ImportPairs() {
			if pair[0] == schema.GeneratedTypesModule {
				generated[pair[1]] = true
				continue
			}
			addModule(pair[0], pair[1])
		}
		if field.ForeignKey != "" {
			addModule(schema.ModuleSQLAlchemy, "ForeignKey")
		}
	}

	if len(model.Indexes) > 0 {
		addModule(schema.ModuleSQLAlchemy, "Index")
		for _, index := range model.Indexes {
			if index.WhereSQL != "" || len(index.Expressions) > 0 {
				addModule(schema.ModuleSQLAlchemy, "text")
			}
		}
	}
	if len(model.UniqueConstraints) > 0 {
		addModule(schema.ModuleSQLAlchemy, "UniqueConstraint")
	}
	if len(model.Relationships) > 0 {
		addModule("sqlalchemy.orm", "relationship")
	}
	if model.Unlogged {
		addModule(schema.ModuleSQLAlchemy, "event")
		addModule(schema.ModuleSQLAlchemy, "text")
	}

	modules := make([]string, 0, len(byModule))
	for module := range byModule {
		modules = append(modules, module)
	}
	sort.Strings(modules)

	lines := make([]string, 0, len(modules)+3)
	for _, module := range modules {
		lines = append(lines, fmt.Sprintf("from %s import %s",
			module, joinSorted(byModule[module])))
	}

	defaults := map[string]bool{}
	for _, field := range model.Fields {
		if field.DefaultImport != "" {
			defaults[field.DefaultImport] = true
		}
	}
	lines = append(lines, sortedSlice(defaults)...)

	prefix := strings.Repeat(".", moduleDepth(model)+1)
	if len(generated) > 0 {
		lines = append(lines, fmt.Sprintf("from %s%s import %s",
			prefix, schema.GeneratedTypesModule, joinSorted(generated)))
	}
	lines = append(lines, fmt.Sprintf("from %sbase import Base", prefix))
	return lines
}

// ── 小工具 ───────────────────────────────────────────────────────────

func modelPath(model schema.Model) string {
	if model.Module != "" {
		return model.Module + "/" + schema.ToModuleName(model.Name) + ".py"
	}
	return schema.ToModuleName(model.Name) + ".py"
}

func moduleDepth(model schema.Model) int {
	if model.Module == "" {
		return 0
	}
	return len(strings.Split(model.Module, "/"))
}

func collectModules(models []schema.Model) []string {
	seen := map[string]bool{}
	modules := make([]string, 0, len(models))
	for _, model := range models {
		if model.Module != "" && !seen[model.Module] {
			seen[model.Module] = true
			modules = append(modules, model.Module)
		}
	}
	sort.Strings(modules)
	return modules
}

func filterByModule(models []schema.Model, module string) []schema.Model {
	result := make([]schema.Model, 0, len(models))
	for _, model := range models {
		if model.Module == module {
			result = append(result, model)
		}
	}
	return result
}

func collectGeneratedNames(models []schema.Model) []string {
	seen := map[string]bool{}
	names := make([]string, 0, 4)
	for _, model := range models {
		for _, field := range model.Fields {
			for _, name := range field.Type.GeneratedNames() {
				if !seen[name] {
					seen[name] = true
					names = append(names, name)
				}
			}
		}
	}
	sort.Strings(names)
	return names
}

func exportedNames(models []schema.Model) []string {
	seen := map[string]bool{"Base": true}
	for _, model := range models {
		seen[model.Name] = true
	}
	return sortedSlice(seen)
}

func quotedList(values []string) []string {
	result := make([]string, 0, len(values))
	for _, value := range values {
		result = append(result, schema.PyRepr(value))
	}
	return result
}

func quotedSorted(values []string) string {
	sorted := append([]string(nil), values...)
	sort.Strings(sorted)
	quoted := make([]string, 0, len(sorted))
	for _, value := range sorted {
		quoted = append(quoted, `"`+value+`"`)
	}
	return strings.Join(quoted, ", ")
}

func joinSorted(values map[string]bool) string {
	return strings.Join(sortedSlice(values), ", ")
}

func sortedSlice(values map[string]bool) []string {
	result := make([]string, 0, len(values))
	for value := range values {
		result = append(result, value)
	}
	sort.Strings(result)
	return result
}

func pyBool(value bool) string {
	if value {
		return "True"
	}
	return "False"
}
