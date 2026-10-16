"""models.yaml 的加载、校验与规范化。

这是所有外部输入的**唯一**入口：任何最终会写进生成代码的字符串，
都在这一层被校验（标识符白名单）或转义（写入模板上下文时用 repr），
模板本身不再承担转义职责，因此不存在模板注入面。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError
from .naming import RESERVED_NAMES, is_valid_identifier, to_module_name, to_table_name
from .types import ColumnType, parse_type

DEFAULT_MIGRATIONS_DIR = "migrations"
DEFAULT_OUTPUT_DIR = "models"

# ── default 表达式白名单 ─────────────────────────────────────────────

_SQL_FUNC_CALL = re.compile(r"^func\.([A-Za-z_][A-Za-z0-9_]*)\(\)$")
_ALLOWED_SQL_FUNCS = frozenset(
    {
        "now",
        "current_timestamp",
        "current_date",
        "current_time",
        "random",
        "uuid_generate_v4",
        "gen_random_uuid",
    }
)

#: 允许的 Python 可调用默认值 -> (生成代码中的表达式, 需要追加的 import)
_ALLOWED_CALLABLES = {
    "datetime.utcnow": ("datetime.utcnow", "from datetime import datetime"),
    "datetime.now": ("datetime.now()", "from datetime import datetime"),
    "uuid.uuid4": ("uuid.uuid4", "import uuid"),
}

_LOOKS_LIKE_EXPRESSION = re.compile(r"[().]")
_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_FOREIGN_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")

# ── 索引选项 ─────────────────────────────────────────────────────────

#: PostgreSQL 索引方法（CREATE INDEX ... USING ...）
PG_INDEX_METHODS = frozenset({"btree", "hash", "gist", "gin", "brin", "spgist"})
#: MySQL 索引前缀类型
MYSQL_INDEX_PREFIXES = frozenset({"fulltext", "spatial"})

_OPCLASS = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$")

#: 表达式索引允许的函数（函数名(列名) 或裸列名）
ALLOWED_INDEX_FUNCTIONS = frozenset(
    {"lower", "upper", "trim", "ltrim", "rtrim", "length", "abs", "date", "md5"}
)
INDEX_EXPRESSION = re.compile(
    r"^(?:"
    r"(?P<func>[A-Za-z_][A-Za-z0-9_]*)\((?P<arg>[A-Za-z_][A-Za-z0-9_]*)\)"
    r"|(?P<plain>[A-Za-z_][A-Za-z0-9_]*)"
    r")$"
)

#: PostgreSQL DOMAIN 名（可带模式前缀）
DOMAIN_NAME = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$"
)

# ── 部分索引条件（index.where）─────────────────────────────────────
# 只接受“列 IS [NOT] NULL”与“列 比较符 字面量”，用 AND/OR 连接。
# 解析后按结构化结果重新拼装，用户输入不会以原始形式进入 SQL。

WHERE_TERM_NULL = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*)\s+IS\s+(NOT\s+)?NULL$", re.IGNORECASE
)
WHERE_TERM_COMPARISON = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*)\s*(<=|>=|<>|!=|=|<|>)\s*(.+)$"
)
WHERE_LITERAL_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
WHERE_LITERAL_BOOL = re.compile(r"^(true|false|null)$", re.IGNORECASE)
WHERE_LITERAL_STRING = re.compile(r"^'(?:[^']|'')*'$")
WHERE_JOIN = re.compile(r"\s+(AND|OR)\s+", re.IGNORECASE)
WHERE_FORBIDDEN = (";", "--", "/*", "*/", "(", ")", ",")


# ── 数据模型 ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Field:
    """一个模型字段。``name`` 已确认是合法 Python 标识符。"""

    name: str
    column: str
    column_explicit: bool
    type: ColumnType
    nullable: bool
    primary_key: bool
    autoincrement: bool
    unique: bool
    index: bool
    default_sql: str | None
    default_import: str | None
    doc: str
    foreign_key: str | None

    @property
    def doc_repr(self) -> str:
        return repr(self.doc)

    @property
    def column_repr(self) -> str:
        return repr(self.column)

    @property
    def foreign_key_repr(self) -> str:
        return repr(self.foreign_key or "")


@dataclass(frozen=True)
class Index:
    name: str
    columns: tuple[str, ...]
    unique: bool
    #: PostgreSQL 索引方法：btree / hash / gist / gin / brin / spgist
    using: str | None = None
    #: PostgreSQL 操作符类：((列名, opclass), ...)
    ops: tuple[tuple[str, str], ...] = ()
    #: PostgreSQL 部分索引条件（已规范化的 SQL 片段）
    where_sql: str | None = None
    #: MySQL 索引前缀：fulltext / spatial
    prefix: str | None = None
    #: MySQL 前缀索引长度：((列名, 长度), ...)
    lengths: tuple[tuple[str, int], ...] = ()
    #: 表达式索引的片段（已规范化），例如 ``("lower(email)",)``
    expressions: tuple[str, ...] = ()
    #: PostgreSQL：CREATE INDEX CONCURRENTLY
    concurrently: bool = False

    @property
    def name_repr(self) -> str:
        return repr(self.name)

    @property
    def column_reprs(self) -> tuple[str, ...]:
        return tuple(repr(column) for column in self.columns)


@dataclass(frozen=True)
class UniqueConstraint:
    name: str | None
    columns: tuple[str, ...]

    @property
    def name_repr(self) -> str:
        return repr(self.name) if self.name else "None"

    @property
    def column_reprs(self) -> tuple[str, ...]:
        return tuple(repr(column) for column in self.columns)


@dataclass(frozen=True)
class Model:
    name: str
    table: str
    description: str
    module: str
    fields: tuple[Field, ...]
    indexes: tuple[Index, ...]
    unique_constraints: tuple[UniqueConstraint, ...]
    #: PostgreSQL：UNLOGGED 表
    unlogged: bool = False

    @property
    def module_name(self) -> str:
        return to_module_name(self.name)

    @property
    def table_repr(self) -> str:
        return repr(self.table)

    @property
    def description_repr(self) -> str:
        return repr(self.description)

    @property
    def primary_key_fields(self) -> tuple[Field, ...]:
        return tuple(field for field in self.fields if field.primary_key)


@dataclass(frozen=True)
class ProjectInfo:
    name: str
    version: str


@dataclass(frozen=True)
class DatabaseInfo:
    url: str | None
    dialect: str | None
    pool_size: int | None
    echo: bool


@dataclass(frozen=True)
class MigrationInfo:
    directory: str
    template: str | None


@dataclass(frozen=True)
class ThirdPartyMapping:
    project: str
    version: str
    db_revision: str


@dataclass(frozen=True)
class GefjonConfig:
    source_path: Path
    project: ProjectInfo
    database: DatabaseInfo
    migration: MigrationInfo
    models: tuple[Model, ...]
    third_party: tuple[ThirdPartyMapping, ...]


# ── 加载 ─────────────────────────────────────────────────────────────


def load_config(path: Path) -> GefjonConfig:
    """读取并校验 models.yaml。"""
    if not path.exists():
        raise ConfigError(f"找不到配置文件：{path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"配置文件 {path} 不是合法 YAML：{exc}") from None

    if not isinstance(raw, dict):
        raise ConfigError(f"配置文件 {path} 的顶层必须是映射")

    database = _parse_database(raw)
    return GefjonConfig(
        source_path=path,
        project=_parse_project(raw),
        database=database,
        migration=_parse_migration(raw),
        models=_parse_models(raw.get("models"), dialect=database.dialect),
        third_party=_parse_third_party(raw.get("mapping")),
    )


def _parse_project(raw: dict[str, Any]) -> ProjectInfo:
    project = raw.get("project") or {}
    if not isinstance(project, dict):
        raise ConfigError("project 必须是映射")
    name = project.get("name") or "gefjon-project"
    # 顶层 version 与 project.version 都接受
    version = project.get("version") or raw.get("version") or "0.0.0"
    return ProjectInfo(name=str(name), version=str(version))


def _parse_database(raw: dict[str, Any]) -> DatabaseInfo:
    database = raw.get("database") or {}
    if not isinstance(database, dict):
        raise ConfigError("database 必须是映射")
    pool_size = database.get("pool_size")
    if pool_size is not None and (not isinstance(pool_size, int) or pool_size <= 0):
        raise ConfigError("database.pool_size 必须是正整数")
    url = database.get("url")
    return DatabaseInfo(
        url=str(url) if url else None,
        dialect=str(database["dialect"]) if database.get("dialect") else None,
        pool_size=pool_size,
        echo=bool(database.get("echo", False)),
    )


def _parse_migration(raw: dict[str, Any]) -> MigrationInfo:
    migration = raw.get("migration") or {}
    if not isinstance(migration, dict):
        raise ConfigError("migration 必须是映射")
    directory = migration.get("directory") or DEFAULT_MIGRATIONS_DIR
    template = migration.get("template")
    return MigrationInfo(
        directory=str(directory),
        template=str(template) if template else None,
    )


def _parse_models(raw_models: Any, *, dialect: str | None = None) -> tuple[Model, ...]:
    if raw_models is None:
        return ()
    if isinstance(raw_models, dict):
        raise ConfigError(
            "models 必须是列表，例如：\n"
            "models:\n"
            "  - name: User\n"
            "    table: users\n"
            "    fields:\n"
            "      - name: id\n"
            "        type: Integer\n"
            "        primary_key: true"
        )
    if not isinstance(raw_models, list):
        raise ConfigError("models 必须是列表")

    models: list[Model] = []
    seen: set[str] = set()
    for entry in raw_models:
        model = _parse_model(entry, dialect=dialect)
        if model.name in seen:
            raise ConfigError(f"模型名重复：{model.name}")
        if model.table in {existing.table for existing in models}:
            raise ConfigError(f"表名重复：{model.table}")
        seen.add(model.name)
        models.append(model)
    return tuple(models)


def _parse_model(entry: Any, *, dialect: str | None = None) -> Model:
    if not isinstance(entry, dict):
        raise ConfigError(f"模型定义必须是映射，收到：{entry!r}")

    name = entry.get("name")
    if not isinstance(name, str) or not is_valid_identifier(name):
        raise ConfigError(f"模型名 {name!r} 不是合法的 Python 类名")

    table = to_table_name(name, entry.get("table"))
    if not _TABLE_NAME.match(table):
        raise ConfigError(f"表名 {table!r} 非法：只允许字母、数字、下划线和点")

    module = str(entry.get("module") or "").strip().replace("\\", "/").strip("/")
    unlogged = entry.get("unlogged", False)
    if not isinstance(unlogged, bool):
        raise ConfigError(f"模型 {name} 的 unlogged 必须是布尔值")
    fields = _parse_fields(entry.get("fields"), name, dialect=dialect)
    field_names = {field.name for field in fields}
    column_names = [field.column for field in fields]

    indexes = _parse_indexes(entry.get("indexes"), table, field_names)
    constraints = _parse_unique_constraints(
        entry.get("unique_constraints"), field_names
    )

    return Model(
        name=name,
        table=table,
        description=str(entry.get("description") or name),
        module=module,
        fields=fields,
        indexes=indexes,
        unique_constraints=constraints,
        unlogged=unlogged,
    )


def _parse_fields(
    raw_fields: Any, model_name: str, *, dialect: str | None = None
) -> tuple[Field, ...]:
    if not isinstance(raw_fields, list) or not raw_fields:
        raise ConfigError(f"模型 {model_name} 必须提供非空的 fields 列表")

    fields: list[Field] = []
    seen_attributes: set[str] = set()
    seen_columns: set[str] = set()
    for raw_field in raw_fields:
        field = _parse_field(raw_field, model_name, dialect=dialect)
        if field.name in seen_attributes:
            raise ConfigError(f"模型 {model_name} 的字段名重复：{field.name}")
        if field.column in seen_columns:
            raise ConfigError(f"模型 {model_name} 的列名重复：{field.column}")
        seen_attributes.add(field.name)
        seen_columns.add(field.column)
        fields.append(field)
    return tuple(fields)


def _parse_field(
    raw_field: Any, model_name: str, *, dialect: str | None = None
) -> Field:
    if not isinstance(raw_field, dict):
        raise ConfigError(f"模型 {model_name} 的字段定义必须是映射：{raw_field!r}")

    raw_name = raw_field.get("name")
    if not isinstance(raw_name, str) or not raw_name:
        raise ConfigError(f"模型 {model_name} 存在缺少 name 的字段")
    if not is_valid_identifier(raw_name):
        raise ConfigError(
            f"模型 {model_name} 的字段名 {raw_name!r} 不是合法的 Python 标识符"
        )

    # 与 SQLAlchemy 声明式基类属性冲突的名字改写到 extra_ 前缀，
    # 数据库列名保持用户声明。
    explicit_column = raw_field.get("column")
    if explicit_column is not None:
        if not isinstance(explicit_column, str) or not explicit_column:
            raise ConfigError(f"字段 {raw_name} 的 column 必须是非空字符串")
        python_name = raw_name
        column = str(explicit_column)
        column_explicit = True
    elif raw_name in RESERVED_NAMES:
        python_name = f"extra_{raw_name}"
        column = raw_name
        column_explicit = True
    else:
        python_name = raw_name
        column = raw_name
        column_explicit = False

    max_length = raw_field.get("maxLength", raw_field.get("max_length"))
    if max_length is not None and (
        not isinstance(max_length, int) or max_length <= 0
    ):
        raise ConfigError(f"字段 {raw_name} 的 maxLength 必须是正整数")
    values = raw_field.get("values")
    if values is not None:
        if not isinstance(values, list) or not values:
            raise ConfigError(f"字段 {raw_name} 的 values 必须是非空列表")
        if not all(isinstance(value, (str, int, float, bool)) for value in values):
            raise ConfigError(f"字段 {raw_name} 的 values 只能是字符串或数字")
        values = [str(value) for value in values]

    timezone = raw_field.get("timezone")
    if timezone is not None and not isinstance(timezone, bool):
        raise ConfigError(f"字段 {raw_name} 的 timezone 必须是布尔值")

    domain_name = raw_field.get("domain_name")
    if domain_name is not None and (
        not isinstance(domain_name, str) or not DOMAIN_NAME.match(domain_name)
    ):
        raise ConfigError(
            f"字段 {raw_name} 的 domain_name 非法（只允许标识符，可带模式前缀）"
        )

    not_null = raw_field.get("not_null")
    if not_null is not None and not isinstance(not_null, bool):
        raise ConfigError(f"字段 {raw_name} 的 not_null 必须是布尔值")

    column_type = parse_type(
        raw_field.get("type"),
        max_length=max_length,
        dialect=dialect,
        values=values,
        item_type=raw_field.get("item_type"),
        timezone=timezone,
        domain_name=domain_name,
        not_null=not_null,
    )

    primary_key = bool(raw_field.get("primary_key", False))
    nullable = bool(raw_field.get("nullable", False))
    if primary_key:
        nullable = False

    if "autoincrement" in raw_field:
        autoincrement = bool(raw_field["autoincrement"])
    else:
        autoincrement = primary_key and column_type.import_name in {
            "Integer",
            "BigInteger",
            "SmallInteger",
        }

    default_sql, default_import = _parse_default(raw_field, raw_name)

    foreign_key = raw_field.get("foreign_key")
    if foreign_key is not None:
        if not isinstance(foreign_key, str) or not _FOREIGN_KEY.match(foreign_key):
            raise ConfigError(
                f"字段 {raw_name} 的 foreign_key 必须形如 表名.列名，收到 {foreign_key!r}"
            )

    return Field(
        name=python_name,
        column=column,
        column_explicit=column_explicit,
        type=column_type,
        nullable=nullable,
        primary_key=primary_key,
        autoincrement=autoincrement,
        unique=bool(raw_field.get("unique", False)),
        index=bool(raw_field.get("index", False)),
        default_sql=default_sql,
        default_import=default_import,
        doc=str(raw_field.get("description") or raw_field.get("doc") or raw_name),
        foreign_key=foreign_key,
    )


def _parse_default(raw_field: dict[str, Any], field_name: str) -> tuple[str | None, str | None]:
    """把 default 解析成安全的源码片段。

    只有白名单里的形式会被当作表达式；其它字符串一律作为**字符串字面量**
    处理（经 repr 转义）。看起来像表达式但不在白名单的输入会直接报错，
    而不是静默变成字符串。
    """
    if "default" not in raw_field:
        return None, None
    value = raw_field["default"]

    if isinstance(value, bool):
        return repr(value), None
    if isinstance(value, (int, float)):
        return repr(value), None
    if value is None:
        return None, None

    if not isinstance(value, str):
        raise ConfigError(f"字段 {field_name} 的 default 类型不受支持：{value!r}")

    text = value.strip()
    if text == "":
        return "''", None

    func_match = _SQL_FUNC_CALL.match(text)
    if func_match:
        func_name = func_match.group(1)
        if func_name not in _ALLOWED_SQL_FUNCS:
            raise ConfigError(
                f"字段 {field_name} 的 default 使用了不支持的函数 func.{func_name}()；"
                f"可用：{', '.join(sorted(_ALLOWED_SQL_FUNCS))}"
            )
        return text, "from sqlalchemy.sql import func"

    callable_match = _ALLOWED_CALLABLES.get(text.rstrip("()"))
    if callable_match and text.rstrip("()") in _ALLOWED_CALLABLES:
        expression, import_line = callable_match
        return expression, import_line

    if _LOOKS_LIKE_EXPRESSION.search(text):
        raise ConfigError(
            f"字段 {field_name} 的 default={text!r} 看起来是表达式，但不在允许的白名单内。"
            f"若要作为字符串字面量，请写成引用形式（例如 default: \"'{text}'\"）。"
        )

    return repr(text), None


def _normalize_where_literal(literal: str, term: str) -> str:
    if WHERE_LITERAL_NUMBER.match(literal):
        return literal
    if WHERE_LITERAL_BOOL.match(literal):
        return literal.upper()
    if WHERE_LITERAL_STRING.match(literal):
        # 已是合法的 SQL 字符串字面量（内部单引号已双写），原样使用
        return literal
    raise ConfigError(
        f"index.where 的字面量 {literal!r} 不被支持"
        f"（只允许数字、'字符串'、true/false/null）：{term!r}"
    )


def _require_where_column(name: str, columns: set[str], term: str) -> str:
    if name not in columns:
        raise ConfigError(
            f"index.where 引用了不在该索引 columns 里的列 {name!r}：{term!r}"
        )
    return name


def _normalize_where_term(term: str, columns: set[str]) -> str:
    term = term.strip()

    null_match = WHERE_TERM_NULL.match(term)
    if null_match is not None:
        column = _require_where_column(null_match.group(1), columns, term)
        return f"{column} IS {'NOT ' if null_match.group(2) else ''}NULL"

    comparison = WHERE_TERM_COMPARISON.match(term)
    if comparison is None:
        raise ConfigError(
            f"不支持的 index.where 片段 {term!r}：只支持“列 IS [NOT] NULL”"
            "或“列 比较符 字面量”，并用 AND / OR 连接"
        )
    column = _require_where_column(comparison.group(1), columns, term)
    operator = comparison.group(2)
    if operator == "!=":
        operator = "<>"
    literal = _normalize_where_literal(comparison.group(3).strip(), term)
    return f"{column} {operator} {literal}"


def _normalize_partial_where(expression: Any, columns: set[str]) -> str:
    """把 ``index.where`` 规范化成安全的 SQL 片段。"""
    if not isinstance(expression, str) or not expression.strip():
        raise ConfigError("index 的 where 必须是非空字符串")

    text = expression.strip()
    for token in WHERE_FORBIDDEN:
        if token in text:
            raise ConfigError(f"index 的 where 不允许出现 {token!r}：{expression!r}")

    parts = WHERE_JOIN.split(text)
    if len(parts) % 2 == 0:
        raise ConfigError(f"index 的 where 连接符使用有误：{expression!r}")

    rendered: list[str] = []
    for position, part in enumerate(parts):
        if position % 2 == 1:
            rendered.append("AND" if part.upper() == "AND" else "OR")
        else:
            rendered.append(_normalize_where_term(part, columns))
    return " ".join(rendered)


def _parse_index_ops(
    raw_ops: Any, column_names: list[str]
) -> tuple[tuple[str, str], ...]:
    if raw_ops is None:
        return ()
    if not isinstance(raw_ops, dict):
        raise ConfigError("index 的 ops 必须是 列名: 操作符类 的映射")
    result: list[tuple[str, str]] = []
    for column, opclass in raw_ops.items():
        if column not in column_names:
            raise ConfigError(f"index 的 ops 引用了不在 columns 里的列 {column!r}")
        if not isinstance(opclass, str) or not _OPCLASS.match(opclass):
            raise ConfigError(
                f"index 的操作符类 {opclass!r} 非法（只允许标识符，可带模式前缀）"
            )
        result.append((column, opclass))
    return tuple(result)


def _parse_index_lengths(
    raw_lengths: Any, column_names: list[str]
) -> tuple[tuple[str, int], ...]:
    if raw_lengths is None:
        return ()
    if not isinstance(raw_lengths, dict):
        raise ConfigError("index 的 lengths 必须是 列名: 长度 的映射")
    result: list[tuple[str, int]] = []
    for column, length in raw_lengths.items():
        if column not in column_names:
            raise ConfigError(f"index 的 lengths 引用了不在 columns 里的列 {column!r}")
        if not isinstance(length, int) or isinstance(length, bool) or length <= 0:
            raise ConfigError(f"index 的 lengths[{column}] 必须是正整数")
        result.append((column, length))
    return tuple(result)


def _slugify(expressions: tuple[str, ...]) -> str:
    parts = [
        re.sub(r"[^0-9a-z]+", "_", expression.lower()).strip("_")
        for expression in expressions
    ]
    joined = "_".join(part for part in parts if part)
    return joined or "expr"


def _parse_index_expressions(raw: Any, field_names: set[str]) -> tuple[str, ...]:
    """解析表达式索引：只允许 ``列名`` 或 ``白名单函数(列名)``。

    解析后按结构化结果重新拼装，因此不会把原始输入直接写进 SQL。
    """
    if raw is None:
        return ()
    if not isinstance(raw, list) or not raw:
        raise ConfigError("index 的 expressions 必须是非空列表")

    result: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(f"index 的表达式必须是非空字符串：{item!r}")
        expression = item.strip()
        match = INDEX_EXPRESSION.match(expression)
        if match is None:
            raise ConfigError(
                f"不支持的索引表达式 {expression!r}：只支持 列名 或 函数(列名)"
            )
        if match.group("func"):
            func = match.group("func").lower()
            if func not in ALLOWED_INDEX_FUNCTIONS:
                raise ConfigError(
                    f"不支持的索引函数 {func!r}：可用 "
                    f"{', '.join(sorted(ALLOWED_INDEX_FUNCTIONS))}"
                )
            column = match.group("arg")
            _validate_columns([column], field_names, "index 表达式")
            result.append(f"{func}({column})")
        else:
            column = match.group("plain")
            _validate_columns([column], field_names, "index 表达式")
            result.append(column)
    return tuple(result)


def _parse_indexes(
    raw_indexes: Any, table: str, field_names: set[str]
) -> tuple[Index, ...]:
    if raw_indexes is None:
        return ()
    if not isinstance(raw_indexes, list):
        raise ConfigError("indexes 必须是列表")

    indexes: list[Index] = []
    for raw_index in raw_indexes:
        if not isinstance(raw_index, dict):
            raise ConfigError(f"index 定义必须是映射：{raw_index!r}")
        expressions = _parse_index_expressions(
            raw_index.get("expressions"), field_names
        )
        columns = raw_index.get("columns")
        if (not isinstance(columns, list) or not columns) and not expressions:
            raise ConfigError("index 必须提供非空的 columns 或 expressions")
        column_names = (
            _validate_columns(columns, field_names, "index")
            if isinstance(columns, list) and columns
            else []
        )

        if raw_index.get("name"):
            name = str(raw_index["name"])
        elif column_names:
            name = f"ix_{table}_{'_'.join(column_names)}"
        else:
            name = f"ix_{table}_{_slugify(expressions)}"

        concurrently = raw_index.get("concurrently", False)
        if not isinstance(concurrently, bool):
            raise ConfigError("index 的 concurrently 必须是布尔值")

        using = raw_index.get("using")
        if using is not None:
            if not isinstance(using, str) or using.lower() not in PG_INDEX_METHODS:
                raise ConfigError(
                    f"index 的 using 只支持 {', '.join(sorted(PG_INDEX_METHODS))}，"
                    f"收到 {using!r}"
                )
            using = using.lower()

        prefix = raw_index.get("prefix")
        if prefix is not None:
            if not isinstance(prefix, str) or prefix.lower() not in MYSQL_INDEX_PREFIXES:
                raise ConfigError(
                    f"index 的 prefix 只支持 {', '.join(sorted(MYSQL_INDEX_PREFIXES))}，"
                    f"收到 {prefix!r}"
                )
            prefix = prefix.lower()

        where_sql = None
        if raw_index.get("where") is not None:
            where_sql = _normalize_partial_where(
                raw_index["where"], set(column_names)
            )

        indexes.append(
            Index(
                name=str(name),
                columns=tuple(column_names),
                unique=bool(raw_index.get("unique", False)),
                using=using,
                ops=_parse_index_ops(raw_index.get("ops"), column_names),
                where_sql=where_sql,
                prefix=prefix,
                lengths=_parse_index_lengths(raw_index.get("lengths"), column_names),
                expressions=expressions,
                concurrently=concurrently,
            )
        )
    return tuple(indexes)


def _parse_unique_constraints(
    raw_constraints: Any, field_names: set[str]
) -> tuple[UniqueConstraint, ...]:
    if raw_constraints is None:
        return ()
    if not isinstance(raw_constraints, list):
        raise ConfigError("unique_constraints 必须是列表")

    constraints: list[UniqueConstraint] = []
    for raw_constraint in raw_constraints:
        if not isinstance(raw_constraint, dict):
            raise ConfigError(f"unique_constraint 定义必须是映射：{raw_constraint!r}")
        columns = raw_constraint.get("columns")
        if not isinstance(columns, list) or not columns:
            raise ConfigError("unique_constraint 必须提供非空的 columns 列表")
        column_names = _validate_columns(columns, field_names, "unique_constraint")
        name = raw_constraint.get("name")
        constraints.append(
            UniqueConstraint(
                name=str(name) if name else None,
                columns=tuple(column_names),
            )
        )
    return tuple(constraints)


def _validate_columns(columns: list[Any], field_names: set[str], kind: str) -> list[str]:
    resolved: list[str] = []
    for column in columns:
        if not isinstance(column, str) or not is_valid_identifier(column):
            raise ConfigError(f"{kind} 的列名 {column!r} 不是合法的字段名")
        attr = f"extra_{column}" if column in RESERVED_NAMES else column
        if attr not in field_names:
            raise ConfigError(
                f"{kind} 引用了不存在的字段 {column!r}；可用字段：{', '.join(sorted(field_names))}"
            )
        resolved.append(column)
    return resolved


def _parse_third_party(raw_mapping: Any) -> tuple[ThirdPartyMapping, ...]:
    if raw_mapping is None:
        return ()
    if not isinstance(raw_mapping, dict):
        raise ConfigError("mapping 必须是映射")
    entries = raw_mapping.get("third_party") or []
    if not isinstance(entries, list):
        raise ConfigError("mapping.third_party 必须是列表")

    mappings: list[ThirdPartyMapping] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ConfigError(f"mapping.third_party 条目必须是映射：{entry!r}")
        missing = [key for key in ("project", "version", "db_revision") if not entry.get(key)]
        if missing:
            raise ConfigError(
                f"mapping.third_party 条目缺少字段：{', '.join(missing)}"
            )
        mappings.append(
            ThirdPartyMapping(
                project=str(entry["project"]),
                version=str(entry["version"]),
                db_revision=str(entry["db_revision"]),
            )
        )
    return tuple(mappings)
