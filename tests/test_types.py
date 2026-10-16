"""types.parse_type 的行为 —— 覆盖通用 / PostgreSQL / MySQL 类型。"""

from __future__ import annotations

import importlib

import pytest

from gefjon.errors import ConfigError
from gefjon.types import MYSQL, POSTGRESQL, SQLALCHEMY, _SPECS, parse_type


@pytest.mark.parametrize(
    ("declaration", "expected"),
    [
        # ── 通用 ──
        ("Integer", "Integer"),
        ("integer", "Integer"),
        ("int", "Integer"),
        ("String(50)", "String(50)"),
        ("String", "String(255)"),
        ("string", "String(255)"),
        ("varchar", "String(255)"),
        ("Text", "Text"),
        ("DateTime", "DateTime"),
        ("datetime", "DateTime"),
        ("timestamp", "DateTime"),
        ("Boolean", "Boolean"),
        ("Numeric(10, 2)", "Numeric(10, 2)"),
        ("decimal", "Numeric"),
        ("BigInteger", "BigInteger"),
        ("uuid", "Uuid"),
        ("UUID", "Uuid"),
        ("JSON", "JSON"),
        ("double", "Float"),
        ("Interval", "Interval"),
        ("PickleType", "PickleType"),
        # ── PostgreSQL 专有（与通用同名的用 pg. 前缀显式指定）──
        ("JSONB", "JSONB"),
        ("jsonb", "JSONB"),
        ("pg.UUID", "UUID"),
        ("PG.JSONPATH", "JSONPATH"),
        ("pg.CITEXT", "CITEXT"),
        ("CITEXT", "CITEXT"),
        ("INET", "INET"),
        ("CIDR", "CIDR"),
        ("MACADDR", "MACADDR"),
        ("MACADDR8", "MACADDR8"),
        ("MONEY", "MONEY"),
        ("BYTEA", "BYTEA"),
        ("HSTORE", "HSTORE"),
        ("TSVECTOR", "TSVECTOR"),
        ("TSQUERY", "TSQUERY"),
        ("varbit(8)", "BIT(8, varying=True)"),
        ("varbit", "BIT(varying=True)"),
        ("INT4RANGE", "INT4RANGE"),
        ("TSTZRANGE", "TSTZRANGE"),
        ("NUMRANGE", "NUMRANGE"),
        ("INT4MULTIRANGE", "INT4MULTIRANGE"),
        ("TSTZMULTIRANGE", "TSTZMULTIRANGE"),
        ("OID", "OID"),
        ("REGCLASS", "REGCLASS"),
        ("REGCONFIG", "REGCONFIG"),
        ("DOUBLE_PRECISION", "DOUBLE_PRECISION"),
        # ── MySQL 专有 ──
        ("TINYINT", "TINYINT"),
        ("MEDIUMINT", "MEDIUMINT"),
        ("YEAR", "YEAR"),
        ("TINYTEXT", "TINYTEXT"),
        ("MEDIUMTEXT", "MEDIUMTEXT"),
        ("LONGTEXT", "LONGTEXT"),
        ("TINYBLOB", "TINYBLOB"),
        ("LONGBLOB", "LONGBLOB"),
        ("mysql.INET4", "INET4"),
        ("mysql.INET6", "INET6"),
        ("VARBINARY(16)", "VARBINARY(16)"),
        ("mysql.DATETIME(6)", "DATETIME(6)"),
        ("DATETIME(6)", "DateTime(6)"),
        ("mysql.DOUBLE(10, 2)", "DOUBLE(10, 2)"),
    ],
)
def test_valid_declarations(declaration: str, expected: str) -> None:
    assert parse_type(declaration).expression == expected


def test_every_registered_type_exists_in_sqlalchemy() -> None:
    """登记的类型名必须在对应模块里真实存在（udt 类型由 Gefjon 生成，跳过）。"""
    missing = [
        f"{spec.module}.{spec.name}"
        for spec in _SPECS
        if not spec.udt
        and not hasattr(importlib.import_module(spec.module), spec.name)
    ]
    assert missing == []


def test_missing_declaration_falls_back_to_string() -> None:
    assert parse_type(None).expression == "String(255)"
    assert parse_type("   ").expression == "String(255)"


def test_max_length_is_used_for_bare_string() -> None:
    assert parse_type("String", max_length=64).expression == "String(64)"


def test_import_module_is_tracked() -> None:
    assert parse_type("Integer").module == SQLALCHEMY
    assert parse_type("JSONB").module == POSTGRESQL
    assert parse_type("TINYTEXT").module == MYSQL
    assert parse_type("pg.JSONB").module == POSTGRESQL


# ── 前缀与方言消歧 ───────────────────────────────────────────────────


def test_explicit_prefix_selects_module() -> None:
    assert parse_type("pg.BIT").module == POSTGRESQL
    assert parse_type("mysql.BIT").module == MYSQL
    assert parse_type("sqlalchemy.Integer").expression == "Integer"


def test_ambiguous_name_requires_prefix_or_dialect() -> None:
    # BIT 在 pg / mysql 都存在，且通用类型里没有，因此必须显式消歧
    with pytest.raises(ConfigError, match="含义不同"):
        parse_type("BIT")


def test_unknown_name_is_rejected() -> None:
    with pytest.raises(ConfigError, match="不支持的类型"):
        parse_type("char_varying")


def test_dialect_resolves_ambiguity() -> None:
    assert parse_type("BIT", dialect="postgresql").module == POSTGRESQL
    assert parse_type("BIT", dialect="mysql").module == MYSQL
    assert parse_type("VARCHAR", dialect="mysql").module == SQLALCHEMY  # 别名优先


def test_generic_wins_for_names_present_in_both() -> None:
    """通用类型（Text / JSON / timestamp / UUID）优先于同名方言类型。"""
    assert parse_type("TEXT").expression == "Text"
    assert parse_type("JSON").module == SQLALCHEMY
    assert parse_type("timestamp").expression == "DateTime"
    assert parse_type("UUID").expression == "Uuid"


def test_types_sqlalchemy_does_not_provide_are_generated() -> None:
    """SQLAlchemy 未内置的几何/空间与 XML 类型由 Gefjon 生成 UserDefinedType 子类。"""
    for declaration in (
        "pg.POINT",
        "pg.POLYGON",
        "pg.XML",
        "mysql.GEOMETRY",
        "mysql.GEOMETRYCOLLECTION",
    ):
        column_type = parse_type(declaration)
        assert column_type.generated is True
        assert column_type.generated_names == (declaration.split(".")[1],)

    # 裸 POINT 在 pg / mysql 都有，仍然需要消歧
    with pytest.raises(ConfigError, match="含义不同"):
        parse_type("POINT")


def test_domain() -> None:
    column_type = parse_type(
        "DOMAIN", item_type="String(5)", domain_name="us_postal_code"
    )
    assert column_type.expression == "DOMAIN('us_postal_code', String(5))"
    assert column_type.module == POSTGRESQL
    assert column_type.generated is False

    assert (
        parse_type(
            "DOMAIN", item_type="Integer", domain_name="positive", not_null=True
        ).expression
        == "DOMAIN('positive', Integer, not_null=True)"
    )

    with pytest.raises(ConfigError, match="domain_name"):
        parse_type("DOMAIN", item_type="Integer")
    with pytest.raises(ConfigError, match="不接受 domain_name"):
        parse_type("Integer", domain_name="x")
    with pytest.raises(ConfigError, match="不接受 not_null"):
        parse_type("Integer", not_null=True)


def test_unknown_prefix_is_rejected() -> None:
    with pytest.raises(ConfigError, match="未知的类型前缀"):
        parse_type("sqlite.TEXT")


# ── 参数 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "declaration",
    [
        "String(abc)",
        "String(1, 2, 3)",
        "Integer(5)",
        "Unknown",
        "String(50); import os",
        "String(50) or __import__('os')",
    ],
)
def test_rejects_bad_declarations(declaration: str) -> None:
    with pytest.raises(ConfigError):
        parse_type(declaration)


def test_enum_requires_values() -> None:
    assert parse_type("Enum", values=["draft", "published"]).expression == (
        "Enum('draft', 'published')"
    )
    with pytest.raises(ConfigError, match="values"):
        parse_type("Enum")


def test_mysql_set_and_enum_take_values() -> None:
    assert parse_type("mysql.SET", values=["a", "b"]).expression == "SET('a', 'b')"
    assert parse_type("mysql.ENUM", values=["x"]).expression == "ENUM('x')"
    assert parse_type("pg.ENUM", values=["x", "y"]).expression == "ENUM('x', 'y')"


def test_values_are_escaped() -> None:
    assert parse_type("Enum", values=["it's"]).expression == "Enum(\"it's\")"


def test_values_rejected_for_other_types() -> None:
    with pytest.raises(ConfigError, match="不接受 values"):
        parse_type("Integer", values=["a"])


def test_array_requires_item_type() -> None:
    assert parse_type("ARRAY", item_type="Text").expression == "ARRAY(Text)"
    assert parse_type("ARRAY", item_type="String(50)").expression == "ARRAY(String(50))"
    assert parse_type("pg.ARRAY", item_type="Integer").expression == "ARRAY(Integer)"
    with pytest.raises(ConfigError, match="item_type"):
        parse_type("ARRAY")


def test_array_item_type_must_not_be_other_dialect() -> None:
    with pytest.raises(ConfigError, match="元素类型"):
        parse_type("pg.ARRAY", item_type="mysql.TINYTEXT")


def test_item_type_rejected_for_other_types() -> None:
    with pytest.raises(ConfigError, match="不接受 item_type"):
        parse_type("Integer", item_type="Text")


def test_timezone_option() -> None:
    assert parse_type("pg.TIMESTAMP", timezone=True).expression == (
        "TIMESTAMP(timezone=True)"
    )
    assert parse_type("DateTime", timezone=True).expression == "DateTime(timezone=True)"
    assert parse_type("DateTime", timezone=False).expression == "DateTime"
    with pytest.raises(ConfigError, match="不接受 timezone"):
        parse_type("Integer", timezone=True)


def test_integer_arguments_are_validated_for_dialect_types() -> None:
    with pytest.raises(ConfigError):
        parse_type("mysql.VARCHAR(abc)")
    with pytest.raises(ConfigError):
        parse_type("pg.MONEY(1)")
