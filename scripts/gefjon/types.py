"""YAML 里的类型声明 -> SQLAlchemy 类型表达式。

类型声明最终会被写进生成的 Python 源码，因此这里坚持白名单：
只有本模块登记的类型名会被接受，参数只能是数字、已校验的字符串列表，
或另一个已校验的类型；其它一律拒绝。

类型目录覆盖三部分：

* **通用类型**（``sqlalchemy``）—— 跨方言可用；
* **PostgreSQL 专有类型**（``sqlalchemy.dialects.postgresql``）——
  JSONB / JSONPATH / UUID / INET / CIDR / MACADDR / TSVECTOR / HSTORE /
  CITEXT / BYTEA / MONEY / 位串 / 范围与多重范围 / 数组 / 枚举等；
* **MySQL 专有类型**（``sqlalchemy.dialects.mysql``）——
  TINYINT / MEDIUMINT / YEAR / TINYTEXT / LONGTEXT / SET / INET4 / INET6 等。

目录里只登记 **SQLAlchemy 真实提供的类型**（有测试逐项 hasattr 校验）。
SQLAlchemy 没有内置的 PostgreSQL / MySQL 几何（空间）类型，也没有 XML 类型，
因此它们不在这里 —— 需要空间类型请引入 geoalchemy2 等扩展，
或把列声明为 ``Text``。PostgreSQL 的 ``bit varying`` 用 ``varbit`` 表达，
渲染为 ``BIT(n, varying=True)``。

当同一个名字在两个方言里含义不同（``BIT``、``POINT`` 等），
要么写成 ``pg.BIT`` / ``mysql.BIT``，要么在 models.yaml 里声明
``database.dialect`` 让解析器按方言挑选。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import ConfigError

SQLALCHEMY = "sqlalchemy"
POSTGRESQL = "sqlalchemy.dialects.postgresql"
MYSQL = "sqlalchemy.dialects.mysql"

#: 类型名前允许的模块前缀
_PREFIXES = {
    "sqlalchemy": SQLALCHEMY,
    "sql": SQLALCHEMY,
    "postgresql": POSTGRESQL,
    "postgres": POSTGRESQL,
    "pg": POSTGRESQL,
    "mysql": MYSQL,
}

#: models.yaml 里 database.dialect 的取值 -> 模块
DIALECT_MODULES = {
    "postgresql": POSTGRESQL,
    "postgres": POSTGRESQL,
    "pg": POSTGRESQL,
    "mysql": MYSQL,
}

DECLARATION = re.compile(
    r"^(?:(?P<prefix>[A-Za-z_][A-Za-z0-9_]*)\.)?"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\((?P<args>[^()]*)\))?$"
)
_INTEGER_ARG = re.compile(r"^\d+$")

#: 未声明类型 / 无长度 String 时的默认长度
DEFAULT_MAX_LENGTH = 255

#: SQLAlchemy 没有内置的方言类型，由 Gefjon 生成到这个辅助模块
GENERATED_TYPES_MODULE = "_gefjon_types"


@dataclass(frozen=True)
class TypeSpec:
    """一个可用类型。"""

    name: str
    module: str = SQLALCHEMY
    dialect: str | None = None
    min_args: int = 0
    max_args: int = 0
    #: 需要 ``values: [...]``（Enum / Set）
    takes_values: bool = False
    #: 需要 ``item_type:``（ARRAY）
    takes_item_type: bool = False
    #: 接受 ``timezone: true``
    takes_timezone: bool = False
    #: 登记用的名字（默认取 name.lower()），用于同一 SQLAlchemy 类型的不同形态
    key: str | None = None
    #: 追加到参数列表末尾的固定关键字参数（如 ``varying=True``）
    extra_args: tuple[str, ...] = ()
    #: 额外可用的别名
    aliases: tuple[str, ...] = ()
    #: SQLAlchemy 未内置，需要 Gefjon 生成 UserDefinedType 子类
    udt: bool = False
    #: 需要 ``domain_name``（PostgreSQL DOMAIN）
    takes_domain: bool = False
    #: 接受 ``not_null``（PostgreSQL DOMAIN）
    takes_not_null: bool = False

    @property
    def registry_key(self) -> str:
        return (self.key or self.name).lower()

    def matches_key(self, lowered: str) -> bool:
        return lowered == self.registry_key or lowered == self.name.lower()


@dataclass(frozen=True)
class ColumnType:
    """一个字段的列类型。"""

    #: 写进生成代码的表达式，例如 ``String(50)`` / ``ARRAY(Text)``
    expression: str
    #: 需要导入的类型名，例如 ``JSONB``
    import_name: str
    #: 该类型所在的模块
    module: str = SQLALCHEMY
    #: 方言（None 表示通用类型）
    dialect: str | None = None
    #: 表达式内部还引用的类型（如 ``ARRAY(Text)`` 里的 ``Text``）
    components: tuple["ColumnType", ...] = ()
    #: 该类型由 Gefjon 生成的辅助模块提供（SQLAlchemy 未内置）
    generated: bool = False

    @property
    def import_pairs(self) -> tuple[tuple[str, str], ...]:
        """``(模块, 类型名)`` 列表，含嵌套类型，用于生成 import。"""
        module = GENERATED_TYPES_MODULE if self.generated else self.module
        pairs: list[tuple[str, str]] = [(module, self.import_name)]
        for component in self.components:
            pairs.extend(component.import_pairs)
        return tuple(pairs)

    @property
    def generated_names(self) -> tuple[str, ...]:
        """需要在辅助模块里生成的类型名（含嵌套）。"""
        names: list[str] = [self.import_name] if self.generated else []
        for component in self.components:
            names.extend(component.generated_names)
        return tuple(names)


# ── 类型目录 ─────────────────────────────────────────────────────────

_GENERIC_SPECS = [
    TypeSpec("Integer", aliases=("int", "integer")),
    TypeSpec("SmallInteger", aliases=("smallint",)),
    TypeSpec("BigInteger", aliases=("bigint",)),
    TypeSpec("String", max_args=1, aliases=("str", "string", "varchar", "char")),
    TypeSpec("Text", max_args=1, aliases=("text",)),
    TypeSpec("Unicode", max_args=1),
    TypeSpec("UnicodeText"),
    TypeSpec("Boolean", aliases=("bool", "boolean")),
    TypeSpec("Date", aliases=("date",)),
    TypeSpec("Time", max_args=1, takes_timezone=True, aliases=("time",)),
    TypeSpec(
        "DateTime",
        max_args=1,
        takes_timezone=True,
        aliases=("datetime", "timestamp"),
    ),
    TypeSpec("Interval", max_args=1, aliases=("interval",)),
    TypeSpec("Float", max_args=1, aliases=("float", "real", "double")),
    TypeSpec("Numeric", max_args=2, aliases=("numeric", "decimal", "number")),
    TypeSpec("JSON", aliases=("json",)),
    TypeSpec("LargeBinary", max_args=1, aliases=("binary", "blob", "largebinary")),
    TypeSpec("Enum", takes_values=True),
    TypeSpec("Uuid", aliases=("uuid",)),
    TypeSpec("ARRAY", takes_item_type=True),
    TypeSpec("PickleType"),
]

_POSTGRESQL_SPECS = [
    # 数值 / 货币
    TypeSpec("SMALLINT", POSTGRESQL, "postgresql"),
    TypeSpec("INTEGER", POSTGRESQL, "postgresql"),
    TypeSpec("BIGINT", POSTGRESQL, "postgresql"),
    TypeSpec("REAL", POSTGRESQL, "postgresql"),
    TypeSpec("FLOAT", POSTGRESQL, "postgresql", max_args=1),
    TypeSpec("DOUBLE_PRECISION", POSTGRESQL, "postgresql", aliases=("doubleprecision",)),
    TypeSpec("NUMERIC", POSTGRESQL, "postgresql", max_args=2),
    TypeSpec("MONEY", POSTGRESQL, "postgresql"),
    # 字符 / 二进制
    TypeSpec("CHAR", POSTGRESQL, "postgresql", max_args=1),
    TypeSpec("VARCHAR", POSTGRESQL, "postgresql", max_args=1),
    TypeSpec("TEXT", POSTGRESQL, "postgresql", max_args=1),
    TypeSpec("CITEXT", POSTGRESQL, "postgresql"),
    TypeSpec("BYTEA", POSTGRESQL, "postgresql"),
    # 日期时间
    TypeSpec("TIMESTAMP", POSTGRESQL, "postgresql", max_args=1, takes_timezone=True),
    TypeSpec("TIME", POSTGRESQL, "postgresql", max_args=1, takes_timezone=True),
    TypeSpec("DATE", POSTGRESQL, "postgresql"),
    TypeSpec("INTERVAL", POSTGRESQL, "postgresql", max_args=1),
    # 布尔
    TypeSpec("BOOLEAN", POSTGRESQL, "postgresql"),
    # 位串：bit 与 bit varying（后者渲染成 BIT(n, varying=True)）
    TypeSpec("BIT", POSTGRESQL, "postgresql", max_args=1),
    TypeSpec(
        "BIT",
        POSTGRESQL,
        "postgresql",
        max_args=1,
        key="varbit",
        extra_args=("varying=True",),
        aliases=("bit_varying",),
    ),
    # 网络地址
    TypeSpec("CIDR", POSTGRESQL, "postgresql"),
    TypeSpec("INET", POSTGRESQL, "postgresql"),
    TypeSpec("MACADDR", POSTGRESQL, "postgresql"),
    TypeSpec("MACADDR8", POSTGRESQL, "postgresql"),
    # UUID / JSON 系
    TypeSpec("UUID", POSTGRESQL, "postgresql"),
    TypeSpec("JSON", POSTGRESQL, "postgresql"),
    TypeSpec("JSONB", POSTGRESQL, "postgresql"),
    TypeSpec("JSONPATH", POSTGRESQL, "postgresql"),
    TypeSpec("HSTORE", POSTGRESQL, "postgresql"),
    # 全文检索
    TypeSpec("TSVECTOR", POSTGRESQL, "postgresql"),
    TypeSpec("TSQUERY", POSTGRESQL, "postgresql"),
    # 范围
    TypeSpec("INT4RANGE", POSTGRESQL, "postgresql"),
    TypeSpec("INT8RANGE", POSTGRESQL, "postgresql"),
    TypeSpec("NUMRANGE", POSTGRESQL, "postgresql"),
    TypeSpec("DATERANGE", POSTGRESQL, "postgresql"),
    TypeSpec("TSRANGE", POSTGRESQL, "postgresql"),
    TypeSpec("TSTZRANGE", POSTGRESQL, "postgresql"),
    # 多重范围
    TypeSpec("INT4MULTIRANGE", POSTGRESQL, "postgresql"),
    TypeSpec("INT8MULTIRANGE", POSTGRESQL, "postgresql"),
    TypeSpec("NUMMULTIRANGE", POSTGRESQL, "postgresql"),
    TypeSpec("DATEMULTIRANGE", POSTGRESQL, "postgresql"),
    TypeSpec("TSMULTIRANGE", POSTGRESQL, "postgresql"),
    TypeSpec("TSTZMULTIRANGE", POSTGRESQL, "postgresql"),
    # 对象标识
    TypeSpec("OID", POSTGRESQL, "postgresql"),
    TypeSpec("REGCLASS", POSTGRESQL, "postgresql"),
    TypeSpec("REGCONFIG", POSTGRESQL, "postgresql"),
    # 复合
    TypeSpec("ARRAY", POSTGRESQL, "postgresql", takes_item_type=True),
    TypeSpec("ENUM", POSTGRESQL, "postgresql", takes_values=True),
    # 域（CREATE DOMAIN）
    TypeSpec(
        "DOMAIN",
        POSTGRESQL,
        "postgresql",
        takes_item_type=True,
        takes_domain=True,
        takes_not_null=True,
    ),
    # 几何与 XML：SQLAlchemy 未内置，由 Gefjon 生成 UserDefinedType 子类
    TypeSpec("POINT", POSTGRESQL, "postgresql", udt=True),
    TypeSpec("LINE", POSTGRESQL, "postgresql", udt=True),
    TypeSpec("LSEG", POSTGRESQL, "postgresql", udt=True),
    TypeSpec("BOX", POSTGRESQL, "postgresql", udt=True),
    TypeSpec("PATH", POSTGRESQL, "postgresql", udt=True),
    TypeSpec("POLYGON", POSTGRESQL, "postgresql", udt=True),
    TypeSpec("CIRCLE", POSTGRESQL, "postgresql", udt=True),
    TypeSpec("XML", POSTGRESQL, "postgresql", udt=True),
]

_MYSQL_SPECS = [
    # 数值
    TypeSpec("TINYINT", MYSQL, "mysql", max_args=1),
    TypeSpec("SMALLINT", MYSQL, "mysql", max_args=1),
    TypeSpec("MEDIUMINT", MYSQL, "mysql", max_args=1),
    TypeSpec("INTEGER", MYSQL, "mysql", max_args=1),
    TypeSpec("BIGINT", MYSQL, "mysql", max_args=1),
    TypeSpec("DECIMAL", MYSQL, "mysql", max_args=2),
    TypeSpec("NUMERIC", MYSQL, "mysql", max_args=2),
    TypeSpec("FLOAT", MYSQL, "mysql", max_args=2),
    TypeSpec("DOUBLE", MYSQL, "mysql", max_args=2),
    TypeSpec("REAL", MYSQL, "mysql", max_args=2),
    TypeSpec("BIT", MYSQL, "mysql", max_args=1),
    TypeSpec("BOOLEAN", MYSQL, "mysql"),
    # 日期时间
    TypeSpec("YEAR", MYSQL, "mysql"),
    TypeSpec("DATE", MYSQL, "mysql"),
    TypeSpec("TIME", MYSQL, "mysql", max_args=1),
    TypeSpec("DATETIME", MYSQL, "mysql", max_args=1),
    TypeSpec("TIMESTAMP", MYSQL, "mysql", max_args=1),
    # 字符串
    TypeSpec("CHAR", MYSQL, "mysql", max_args=1),
    TypeSpec("VARCHAR", MYSQL, "mysql", max_args=1),
    TypeSpec("NCHAR", MYSQL, "mysql", max_args=1),
    TypeSpec("NVARCHAR", MYSQL, "mysql", max_args=1),
    TypeSpec("TINYTEXT", MYSQL, "mysql", max_args=1),
    TypeSpec("TEXT", MYSQL, "mysql", max_args=1),
    TypeSpec("MEDIUMTEXT", MYSQL, "mysql", max_args=1),
    TypeSpec("LONGTEXT", MYSQL, "mysql", max_args=1),
    # 二进制
    TypeSpec("BINARY", MYSQL, "mysql", max_args=1),
    TypeSpec("VARBINARY", MYSQL, "mysql", max_args=1),
    TypeSpec("TINYBLOB", MYSQL, "mysql", max_args=1),
    TypeSpec("BLOB", MYSQL, "mysql", max_args=1),
    TypeSpec("MEDIUMBLOB", MYSQL, "mysql", max_args=1),
    TypeSpec("LONGBLOB", MYSQL, "mysql", max_args=1),
    # 枚举 / 集合
    TypeSpec("ENUM", MYSQL, "mysql", takes_values=True),
    TypeSpec("SET", MYSQL, "mysql", takes_values=True),
    # JSON 与网络地址
    TypeSpec("JSON", MYSQL, "mysql"),
    TypeSpec("INET4", MYSQL, "mysql"),
    TypeSpec("INET6", MYSQL, "mysql"),
    # 空间类型：SQLAlchemy 未内置，由 Gefjon 生成 UserDefinedType 子类
    TypeSpec("GEOMETRY", MYSQL, "mysql", udt=True),
    TypeSpec("POINT", MYSQL, "mysql", udt=True),
    TypeSpec("LINESTRING", MYSQL, "mysql", udt=True),
    TypeSpec("POLYGON", MYSQL, "mysql", udt=True),
    TypeSpec("MULTIPOINT", MYSQL, "mysql", udt=True),
    TypeSpec("MULTILINESTRING", MYSQL, "mysql", udt=True),
    TypeSpec("MULTIPOLYGON", MYSQL, "mysql", udt=True),
    TypeSpec("GEOMETRYCOLLECTION", MYSQL, "mysql", udt=True),
]

_SPECS: list[TypeSpec] = [*_GENERIC_SPECS, *_POSTGRESQL_SPECS, *_MYSQL_SPECS]

#: 名字（登记名 + 别名，均小写）-> 候选类型
_BY_KEY: dict[str, list[TypeSpec]] = {}
for _spec in _SPECS:
    _BY_KEY.setdefault(_spec.registry_key, []).append(_spec)
    for _alias in _spec.aliases:
        _BY_KEY.setdefault(_alias.lower(), []).append(_spec)


def available_type_names() -> list[str]:
    """所有可用类型名（含别名），用于报错提示。"""
    return sorted(_BY_KEY)


def _resolve_spec(raw_name: str, prefix: str | None, dialect: str | None) -> TypeSpec:
    lowered = raw_name.lower()

    if prefix is not None:
        module = _PREFIXES.get(prefix.lower())
        if module is None:
            raise ConfigError(
                f"未知的类型前缀 {prefix!r}；可用前缀：sqlalchemy / pg / mysql"
            )
        candidates = [
            spec
            for spec in _BY_KEY.get(lowered, [])
            if spec.module == module
        ]
        if not candidates:
            raise ConfigError(
                f"模块 {prefix} 下没有类型 {raw_name!r}；可用："
                f"{', '.join(sorted(s.name for s in _SPECS if s.module == module))}"
            )
        return candidates[0]

    candidates = _BY_KEY.get(lowered)
    if not candidates:
        raise ConfigError(
            f"不支持的类型 {raw_name!r}；可用类型：{', '.join(available_type_names())}"
        )
    if len(candidates) == 1:
        return candidates[0]

    # 同名跨方言：通用类型优先，其次按 database.dialect 挑选
    generic = [spec for spec in candidates if spec.dialect is None]
    if generic:
        return generic[0]

    module = DIALECT_MODULES.get((dialect or "").lower())
    if module is not None:
        matched = [spec for spec in candidates if spec.module == module]
        if matched:
            return matched[0]

    dialects = " / ".join(sorted({spec.dialect or "generic" for spec in candidates}))
    raise ConfigError(
        f"类型名 {raw_name!r} 在 {dialects} 中含义不同："
        f"请写成 {candidates[0].dialect}.{candidates[0].name}，"
        "或在 models.yaml 里声明 database.dialect"
    )


def _parse_args(text: str, spec: TypeSpec, declaration: str) -> list[str]:
    if not text.strip():
        return []
    args = [part.strip() for part in text.split(",")]
    for arg in args:
        if not _INTEGER_ARG.match(arg):
            raise ConfigError(f"类型 {declaration!r} 的参数必须是整数，收到 {arg!r}")
    if not (spec.min_args <= len(args) <= spec.max_args):
        raise ConfigError(
            f"类型 {spec.name} 需要 {spec.min_args}~{spec.max_args} 个参数，"
            f"收到 {declaration!r}"
        )
    return args


def parse_type(
    declaration: str | None,
    *,
    max_length: int | None = None,
    dialect: str | None = None,
    values: list[str] | None = None,
    item_type: str | None = None,
    timezone: bool | None = None,
    domain_name: str | None = None,
    not_null: bool | None = None,
) -> ColumnType:
    """把 YAML 的类型声明解析为 :class:`ColumnType`。

    Args:
        declaration: 形如 ``String(50)`` / ``JSONB`` / ``pg.BIT`` / ``mysql.TINYTEXT``。
        max_length: 无参数 ``String`` 的长度，默认 255。
        dialect: models.yaml 里的 ``database.dialect``，用于消解同名类型。
        values: ``Enum`` / ``Set`` / PG ``ENUM`` 的取值列表。
        item_type: ``ARRAY`` 的元素类型声明。
        timezone: ``TIMESTAMP`` / ``TIME`` 是否带时区。

    Raises:
        ConfigError: 类型名不在白名单、参数非法，或缺少必需参数。
    """
    if declaration is None or str(declaration).strip() == "":
        return ColumnType(f"String({max_length or DEFAULT_MAX_LENGTH})", "String")

    text = str(declaration).strip()
    match = DECLARATION.match(text)
    if match is None:
        raise ConfigError(
            f"无法解析字段类型 {declaration!r}："
            "只允许 [前缀.]类型名 或 类型名(数字[, 数字])"
        )

    spec = _resolve_spec(match.group("name"), match.group("prefix"), dialect)
    parts: list[str] = _parse_args(match.group("args") or "", spec, text)
    components: tuple[ColumnType, ...] = ()

    if spec.takes_values:
        if not values:
            raise ConfigError(
                f"类型 {spec.name} 必须提供 values 列表，例如 values: [draft, published]"
            )
        parts = [repr(str(value)) for value in values]
    elif values:
        raise ConfigError(f"类型 {spec.name} 不接受 values")

    if spec.takes_item_type:
        if not item_type:
            raise ConfigError(
                f"类型 {spec.name} 必须提供 item_type，例如 item_type: Text"
            )
        inner = parse_type(item_type, max_length=max_length, dialect=dialect)
        if inner.dialect is not None and inner.dialect != spec.dialect:
            raise ConfigError(
                f"元素类型不能是 {inner.dialect} 专有类型：{item_type!r}"
            )
        parts = [inner.expression]
        components = (inner,)
    elif item_type:
        raise ConfigError(f"类型 {spec.name} 不接受 item_type")

    if spec.takes_domain:
        if not domain_name:
            raise ConfigError(
                f"类型 {spec.name} 必须提供 domain_name，"
                "例如 domain_name: us_postal_code"
            )
        if len(parts) != 1:
            raise ConfigError(f"类型 {spec.name} 需要 item_type 作为基类型")
        parts = [repr(str(domain_name)), parts[0]]
        if not_null:
            parts.append("not_null=True")
    elif domain_name:
        raise ConfigError(f"类型 {spec.name} 不接受 domain_name")
    elif not_null is not None:
        raise ConfigError(f"类型 {spec.name} 不接受 not_null")

    if timezone is not None:
        if not spec.takes_timezone:
            raise ConfigError(f"类型 {spec.name} 不接受 timezone 选项")
        if timezone:
            parts.append("timezone=True")

    parts.extend(spec.extra_args)

    if spec.name == "String" and not parts:
        parts = [str(max_length or DEFAULT_MAX_LENGTH)]

    inner_text = ", ".join(parts)
    expression = f"{spec.name}({inner_text})" if inner_text else spec.name
    return ColumnType(
        expression=expression,
        import_name=spec.name,
        module=spec.module,
        dialect=spec.dialect,
        components=components,
        generated=spec.udt,
    )
