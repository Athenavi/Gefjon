"""config.load_config 的校验行为 —— 覆盖模板注入与语义缺陷。"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from gefjon.config import load_config
from gefjon.errors import ConfigError


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "models.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_parses_project_and_models(project: Path) -> None:
    config = load_config(project / "models.yaml")
    assert config.project.name == "demo"
    assert config.project.version == "1.2.3"
    assert [model.name for model in config.models] == ["User", "Post"]

    user = config.models[0]
    assert user.table == "users"
    assert [field.name for field in user.fields] == [
        "id",
        "username",
        "email",
        "created_at",
    ]

    username = user.fields[1]
    assert username.nullable is False
    assert username.unique is True

    created_at = user.fields[3]
    assert created_at.default_sql == "func.now()"
    assert created_at.default_import == "from sqlalchemy.sql import func"


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yaml")


def test_top_level_version_is_accepted(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        version: 9.9.9
        models:
          - name: Thing
            fields:
              - name: id
                type: Integer
                primary_key: true
        """,
    )
    assert load_config(path).project.version == "9.9.9"


def test_models_as_mapping_is_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          User:
            orm: true
        """,
    )
    with pytest.raises(ConfigError, match="models 必须是列表"):
        load_config(path)


@pytest.mark.parametrize(
    "field_name",
    [
        "class",
        "1bad",
        "has space",
        "x = 1; import os",
        "__import__('os')",
        "",
    ],
)
def test_field_names_must_be_identifiers(tmp_path: Path, field_name: str) -> None:
    path = _write(
        tmp_path,
        f"""
        models:
          - name: Thing
            fields:
              - name: "{field_name}"
                type: Integer
        """,
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_model_name_must_be_identifier(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: "Thing(Base): pass\\nclass Evil"
            fields:
              - name: id
                type: Integer
        """,
    )
    with pytest.raises(ConfigError):
        load_config(path)


@pytest.mark.parametrize(
    "bad_default",
    [
        "os.system('echo pwned')",
        "__import__('os').system('id')",
        "func.evil()",
        "open('/etc/passwd').read()",
    ],
)
def test_default_expressions_are_whitelisted(tmp_path: Path, bad_default: str) -> None:
    path = _write(
        tmp_path,
        f"""
        models:
          - name: Thing
            fields:
              - name: value
                type: String(10)
                default: "{bad_default}"
        """,
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_string_default_is_literal_not_code(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: Thing
            fields:
              - name: status
                type: String(20)
                default: "pending"
        """,
    )
    field = load_config(path).models[0].fields[0]
    assert field.default_sql == "'pending'"


def test_allowed_defaults(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: Thing
            fields:
              - name: created
                type: DateTime
                default: "func.now()"
              - name: updated
                type: DateTime
                default: "datetime.utcnow"
              - name: uid
                type: String(36)
                default: "uuid.uuid4"
              - name: flag
                type: Boolean
                default: false
              - name: count
                type: Integer
                default: 3
        """,
    )
    fields = {field.name: field for field in load_config(path).models[0].fields}
    assert fields["created"].default_sql == "func.now()"
    assert fields["updated"].default_sql == "datetime.utcnow"
    assert fields["uid"].default_sql == "uuid.uuid4"
    assert fields["flag"].default_sql == "False"
    assert fields["count"].default_sql == "3"


def test_reserved_field_name_is_renamed(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: Thing
            fields:
              - name: id
                type: Integer
                primary_key: true
              - name: metadata
                type: String(10)
        """,
    )
    field = load_config(path).models[0].fields[1]
    assert field.name == "extra_metadata"
    assert field.column == "metadata"
    assert field.column_explicit is True


def test_duplicate_names_are_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: Thing
            table: things
            fields:
              - name: id
                type: Integer
                primary_key: true
          - name: Thing
            table: other
            fields:
              - name: id
                type: Integer
                primary_key: true
        """,
    )
    with pytest.raises(ConfigError, match="模型名重复"):
        load_config(path)


def test_index_must_reference_existing_field(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: Thing
            fields:
              - name: id
                type: Integer
                primary_key: true
            indexes:
              - columns: [nope]
        """,
    )
    with pytest.raises(ConfigError, match="不存在的字段"):
        load_config(path)


def test_bad_foreign_key_is_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: Thing
            fields:
              - name: user_id
                type: Integer
                foreign_key: "users.id; DROP TABLE users"
        """,
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_tablename_is_derived_when_missing(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: MediaAsset
            fields:
              - name: id
                type: Integer
                primary_key: true
        """,
    )
    assert load_config(path).models[0].table == "media_assets"


def test_third_party_mapping(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models: []
        mapping:
          third_party:
            - project: auth-service
              version: v2.1.0
              db_revision: abc123
        """,
    )
    mappings = load_config(path).third_party
    assert mappings[0].project == "auth-service"
    assert mappings[0].db_revision == "abc123"


# ── 方言类型 ─────────────────────────────────────────────────────────


def test_postgresql_types_in_model(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        database:
          dialect: postgresql
        models:
          - name: Doc
            fields:
              - name: id
                type: Integer
                primary_key: true
              - name: payload
                type: JSONB
              - name: tags
                type: ARRAY
                item_type: Text
              - name: state
                type: Enum
                values: [draft, published]
              - name: seen_at
                type: pg.TIMESTAMP
                timezone: true
              - name: addr
                type: INET
        """,
    )
    fields = {field.name: field for field in load_config(path).models[0].fields}
    assert fields["payload"].type.expression == "JSONB"
    assert fields["tags"].type.expression == "ARRAY(Text)"
    assert fields["state"].type.expression == "Enum('draft', 'published')"
    assert fields["seen_at"].type.expression == "TIMESTAMP(timezone=True)"
    assert fields["addr"].type.expression == "INET"


def test_mysql_types_in_model(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        database:
          dialect: mysql
        models:
          - name: Doc
            fields:
              - name: id
                type: Integer
                primary_key: true
              - name: body
                type: LONGTEXT
              - name: flags
                type: mysql.SET
                values: [a, b, c]
              - name: year
                type: YEAR
        """,
    )
    fields = {field.name: field for field in load_config(path).models[0].fields}
    assert fields["body"].type.expression == "LONGTEXT"
    assert fields["flags"].type.expression == "SET('a', 'b', 'c')"
    assert fields["year"].type.expression == "YEAR"


def test_enum_without_values_is_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: Doc
            fields:
              - name: state
                type: Enum
        """,
    )
    with pytest.raises(ConfigError, match="values"):
        load_config(path)


def test_values_must_be_scalar_list(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: Doc
            fields:
              - name: state
                type: Enum
                values: [[1, 2]]
        """,
    )
    with pytest.raises(ConfigError, match="values"):
        load_config(path)


def test_timezone_must_be_boolean(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: Doc
            fields:
              - name: seen_at
                type: pg.TIMESTAMP
                timezone: "yes"
        """,
    )
    with pytest.raises(ConfigError, match="timezone"):
        load_config(path)


# ── 索引选项 ─────────────────────────────────────────────────────────


def test_postgresql_index_options(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        database:
          dialect: postgresql
        models:
          - name: Doc
            fields:
              - name: id
                type: Integer
                primary_key: true
              - name: payload
                type: JSONB
              - name: deleted_at
                type: DateTime
                nullable: true
            indexes:
              - columns: [payload]
                using: gin
                ops: {payload: jsonb_path_ops}
              - columns: [deleted_at]
                where: "deleted_at IS NULL"
              - columns: [payload]
                unique: true
                using: brin
        """,
    )
    gin, partial, unique_brin = load_config(path).models[0].indexes
    assert gin.using == "gin"
    assert gin.ops == (("payload", "jsonb_path_ops"),)
    assert partial.where_sql == "deleted_at IS NULL"
    assert unique_brin.unique is True
    assert unique_brin.using == "brin"


def test_partial_where_accepts_supported_forms(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: Doc
            fields:
              - name: id
                type: Integer
                primary_key: true
              - name: deleted_at
                type: DateTime
                nullable: true
              - name: payload
                type: Text
            indexes:
              - columns: [deleted_at, payload]
                where: "deleted_at IS NOT NULL AND payload <> '{}'"
        """,
    )
    index = load_config(path).models[0].indexes[0]
    assert index.where_sql == "deleted_at IS NOT NULL AND payload <> '{}'"


@pytest.mark.parametrize(
    "bad_where",
    [
        "1=1; DROP TABLE users",
        "deleted_at IS NULL -- comment",
        "id = (SELECT 1)",
        "id IN (1,2)",
        "lower(payload) = 'x'",
        "deleted_at IS NOT NULL; DELETE FROM users",
        "id = 1 or 1=1 union select 1",
    ],
)
def test_partial_where_rejects_unsupported_syntax(
    tmp_path: Path, bad_where: str
) -> None:
    path = _write(
        tmp_path,
        f"""
        models:
          - name: Doc
            fields:
              - name: id
                type: Integer
                primary_key: true
              - name: deleted_at
                type: DateTime
                nullable: true
              - name: payload
                type: Text
            indexes:
              - columns: [deleted_at, payload, id]
                where: "{bad_where}"
        """,
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_partial_where_must_reference_indexed_column(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: Doc
            fields:
              - name: id
                type: Integer
                primary_key: true
              - name: other
                type: Integer
                nullable: true
            indexes:
              - columns: [id]
                where: "other IS NULL"
        """,
    )
    with pytest.raises(ConfigError, match="不在该索引 columns 里"):
        load_config(path)


def test_index_using_must_be_known_method(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: Doc
            fields:
              - name: id
                type: Integer
                primary_key: true
            indexes:
              - columns: [id]
                using: "gin; DROP TABLE users"
        """,
    )
    with pytest.raises(ConfigError, match="using"):
        load_config(path)


def test_index_ops_must_be_identifier(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: Doc
            fields:
              - name: id
                type: Integer
                primary_key: true
              - name: payload
                type: JSONB
            indexes:
              - columns: [payload]
                ops: {payload: "jsonb_path_ops) ; DROP TABLE users --"}
        """,
    )
    with pytest.raises(ConfigError, match="操作符类"):
        load_config(path)


def test_mysql_index_prefix_and_lengths(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        database:
          dialect: mysql
        models:
          - name: Doc
            fields:
              - name: id
                type: Integer
                primary_key: true
              - name: body
                type: LONGTEXT
              - name: url
                type: String(500)
            indexes:
              - columns: [body]
                prefix: fulltext
              - columns: [url]
                lengths: {url: 191}
        """,
    )
    fulltext, prefix_index = load_config(path).models[0].indexes
    assert fulltext.prefix == "fulltext"
    assert prefix_index.lengths == (("url", 191),)


def test_mysql_prefix_must_be_known(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: Doc
            fields:
              - name: id
                type: Integer
                primary_key: true
            indexes:
              - columns: [id]
                prefix: nonsense
        """,
    )
    with pytest.raises(ConfigError, match="prefix"):
        load_config(path)


def test_index_lengths_must_be_positive(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: Doc
            fields:
              - name: id
                type: Integer
                primary_key: true
            indexes:
              - columns: [id]
                lengths: {id: 0}
        """,
    )
    with pytest.raises(ConfigError, match="正整数"):
        load_config(path)


# ── UNLOGGED / DOMAIN / 表达式索引 / CONCURRENTLY ────────────────────


def test_model_unlogged_flag(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: Event
            unlogged: true
            fields:
              - name: id
                type: Integer
                primary_key: true
        """,
    )
    assert load_config(path).models[0].unlogged is True


def test_unlogged_must_be_boolean(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: Event
            unlogged: "yes"
            fields:
              - name: id
                type: Integer
                primary_key: true
        """,
    )
    with pytest.raises(ConfigError, match="unlogged"):
        load_config(path)


def test_domain_field(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        database:
          dialect: postgresql
        models:
          - name: Person
            fields:
              - name: id
                type: Integer
                primary_key: true
              - name: postal_code
                type: DOMAIN
                domain_name: us_postal_code
                item_type: String(5)
                not_null: true
        """,
    )
    field = load_config(path).models[0].fields[1]
    assert field.type.expression == "DOMAIN('us_postal_code', String(5), not_null=True)"


def test_domain_name_must_be_identifier(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: Person
            fields:
              - name: postal_code
                type: DOMAIN
                domain_name: "bad-name; DROP TABLE users"
                item_type: String(5)
        """,
    )
    with pytest.raises(ConfigError, match="domain_name"):
        load_config(path)


def test_spatial_type_is_generated(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        database:
          dialect: postgresql
        models:
          - name: Place
            fields:
              - name: id
                type: Integer
                primary_key: true
              - name: location
                type: pg.POINT
              - name: doc
                type: pg.XML
        """,
    )
    fields = {field.name: field for field in load_config(path).models[0].fields}
    assert fields["location"].type.generated is True
    assert fields["doc"].type.generated is True


def test_expression_index(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: User
            fields:
              - name: id
                type: Integer
                primary_key: true
              - name: email
                type: String(100)
            indexes:
              - expressions: ["lower(email)"]
                unique: true
        """,
    )
    index = load_config(path).models[0].indexes[0]
    assert index.expressions == ("lower(email)",)
    assert index.columns == ()
    assert index.unique is True
    assert index.name == "ix_users_lower_email"


def test_expression_index_accepts_plain_column(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: User
            fields:
              - name: id
                type: Integer
                primary_key: true
              - name: email
                type: String(100)
            indexes:
              - expressions: [email]
        """,
    )
    assert load_config(path).models[0].indexes[0].expressions == ("email",)


def test_expression_index_rejects_unknown_function(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: User
            fields:
              - name: id
                type: Integer
                primary_key: true
              - name: email
                type: String(100)
            indexes:
              - expressions: ["evil(email)"]
        """,
    )
    with pytest.raises(ConfigError, match="索引函数"):
        load_config(path)


@pytest.mark.parametrize(
    "bad_expression",
    [
        "lower(email) || 'x'",
        "(SELECT 1)",
        "lower(email); DROP TABLE users",
        "lower(email, 1)",
        "lower(email) -- comment",
    ],
)
def test_expression_index_rejects_unsupported_syntax(
    tmp_path: Path, bad_expression: str
) -> None:
    path = _write(
        tmp_path,
        f"""
        models:
          - name: User
            fields:
              - name: id
                type: Integer
                primary_key: true
              - name: email
                type: String(100)
            indexes:
              - expressions: ["{bad_expression}"]
        """,
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_expression_index_must_reference_existing_column(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: User
            fields:
              - name: id
                type: Integer
                primary_key: true
            indexes:
              - expressions: ["lower(nope)"]
        """,
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_index_concurrently(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: User
            fields:
              - name: id
                type: Integer
                primary_key: true
              - name: email
                type: String(100)
            indexes:
              - columns: [email]
                concurrently: true
        """,
    )
    assert load_config(path).models[0].indexes[0].concurrently is True


def test_index_needs_columns_or_expressions(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        models:
          - name: User
            fields:
              - name: id
                type: Integer
                primary_key: true
            indexes:
              - unique: true
        """,
    )
    with pytest.raises(ConfigError, match="columns 或 expressions"):
        load_config(path)
