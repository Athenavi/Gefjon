"""生成器：落盘行为、语义正确性与“绝不写空文件”保证。"""

from __future__ import annotations

import importlib
import sys
import textwrap
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa

from gefjon import generator
from gefjon.config import load_config
from gefjon.errors import GenerationError
from gefjon.generator import generate_models


def _generate(project: Path, **kwargs):
    config = load_config(project / "models.yaml")
    return generate_models(config, project / "models", project_root=project, **kwargs)


def test_generates_expected_files(project: Path) -> None:
    result = _generate(project)
    output = project / "models"
    assert (output / "base.py").is_file()
    assert (output / "__init__.py").is_file()
    assert (output / "user.py").is_file()
    assert (output / "post.py").is_file()
    assert {item.model for item in result.files} == {"User", "Post"}


def test_generated_sources_are_valid_python(project: Path) -> None:
    _generate(project)
    for path in sorted((project / "models").rglob("*.py")):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")


def test_nullable_false_becomes_not_null(project: Path) -> None:
    _generate(project)
    source = (project / "models" / "user.py").read_text(encoding="utf-8")
    assert "username = Column(String(50), nullable=False, unique=True" in source
    assert "created_at = Column(DateTime, nullable=False, default=func.now()" in source


def test_nullable_true_is_preserved(project: Path) -> None:
    _generate(project)
    source = (project / "models" / "post.py").read_text(encoding="utf-8")
    assert "content = Column(Text, nullable=True" in source


def test_primary_key_is_not_null_and_auto_increments(project: Path) -> None:
    _generate(project)
    source = (project / "models" / "user.py").read_text(encoding="utf-8")
    assert "id = Column(Integer, primary_key=True, autoincrement=True" in source


def test_foreign_key_and_imports(project: Path) -> None:
    _generate(project)
    source = (project / "models" / "post.py").read_text(encoding="utf-8")
    assert "ForeignKey('users.id')" in source
    assert "from sqlalchemy import BigInteger" not in source
    assert "from .base import Base" in source


def test_table_args_and_index(project: Path) -> None:
    _generate(project)
    source = (project / "models" / "user.py").read_text(encoding="utf-8")
    assert "__table_args__ = (" in source
    assert "Index('ix_users_email', 'email', unique=True)" in source


def test_unique_and_index_kept_for_integer_and_boolean(tmp_path: Path) -> None:
    (tmp_path / "models.yaml").write_text(
        textwrap.dedent(
            """
            models:
              - name: Thing
                fields:
                  - name: id
                    type: Integer
                    primary_key: true
                  - name: code
                    type: Integer
                    unique: true
                  - name: flag
                    type: Boolean
                    index: true
            """
        ),
        encoding="utf-8",
    )
    _generate(tmp_path)
    source = (tmp_path / "models" / "thing.py").read_text(encoding="utf-8")
    assert "code = Column(Integer, nullable=False, unique=True" in source
    assert "flag = Column(Boolean, nullable=False, index=True" in source


def test_quotes_and_newlines_in_doc_are_escaped(tmp_path: Path) -> None:
    (tmp_path / "models.yaml").write_text(
        textwrap.dedent(
            """
            models:
              - name: Thing
                fields:
                  - name: id
                    type: Integer
                    primary_key: true
                  - name: value
                    type: String(10)
                    description: "it's a \\"quoted\\" thing"
            """
        ),
        encoding="utf-8",
    )
    _generate(tmp_path)
    source = (tmp_path / "models" / "thing.py").read_text(encoding="utf-8")
    compile(source, "thing.py", "exec")  # 语法必须合法
    assert "doc=" in source


def test_reserved_word_column_name(tmp_path: Path) -> None:
    (tmp_path / "models.yaml").write_text(
        textwrap.dedent(
            """
            models:
              - name: Thing
                fields:
                  - name: id
                    type: Integer
                    primary_key: true
                  - name: metadata
                    type: String(10)
            """
        ),
        encoding="utf-8",
    )
    _generate(tmp_path)
    source = (tmp_path / "models" / "thing.py").read_text(encoding="utf-8")
    assert "extra_metadata = Column('metadata', String(10)" in source


def test_missing_template_raises_and_writes_nothing(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """模板缺失时必须报错，且不留下任何文件（旧实现会写成空文件）。"""
    empty = tmp_path / "empty_templates"
    empty.mkdir()
    monkeypatch.setattr(generator, "TEMPLATES_DIR", empty)

    with pytest.raises(GenerationError, match="模板缺失"):
        _generate(project)

    assert not (project / "models").exists()


def test_failure_keeps_existing_files_intact(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _generate(project)
    original = (project / "models" / "user.py").read_text(encoding="utf-8")
    assert original.strip()

    empty = tmp_path / "empty_templates"
    empty.mkdir()
    monkeypatch.setattr(generator, "TEMPLATES_DIR", empty)

    with pytest.raises(GenerationError):
        _generate(project, backup=False)

    assert (project / "models" / "user.py").read_text(encoding="utf-8") == original


def test_regenerate_creates_backup(project: Path) -> None:
    _generate(project)
    result = _generate(project)
    assert result.backup_dir is not None
    assert result.backup_dir.is_dir()
    assert any(result.backup_dir.rglob("user.py"))


def test_selected_models_only(project: Path) -> None:
    result = _generate(project, selected=["User"])
    assert {item.model for item in result.files} == {"User"}
    assert (project / "models" / "user.py").is_file()
    assert not (project / "models" / "post.py").exists()
    init_source = (project / "models" / "__init__.py").read_text(encoding="utf-8")
    assert "User" in init_source
    assert "Post" not in init_source


def test_unknown_selection_raises(project: Path) -> None:
    with pytest.raises(GenerationError, match="不存在这些模型"):
        _generate(project, selected=["Nope"])


def test_module_subdirectory_layout(tmp_path: Path) -> None:
    (tmp_path / "models.yaml").write_text(
        textwrap.dedent(
            """
            models:
              - name: Token
                module: auth
                fields:
                  - name: id
                    type: Integer
                    primary_key: true
            """
        ),
        encoding="utf-8",
    )
    _generate(tmp_path)
    assert (tmp_path / "models" / "auth" / "token.py").is_file()
    assert (tmp_path / "models" / "auth" / "__init__.py").is_file()
    sub_init = (tmp_path / "models" / "auth" / "__init__.py").read_text(encoding="utf-8")
    assert "Token" in sub_init
    token = (tmp_path / "models" / "auth" / "token.py").read_text(encoding="utf-8")
    assert "from ..base import Base" in token


# ── 方言类型与索引的生成结果 ─────────────────────────────────────────


def test_postgresql_types_generate_dialect_imports(tmp_path: Path) -> None:
    (tmp_path / "models.yaml").write_text(
        textwrap.dedent(
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
                  - name: addr
                    type: INET
                  - name: tags
                    type: ARRAY
                    item_type: Text
            """
        ),
        encoding="utf-8",
    )
    _generate(tmp_path)
    source = (tmp_path / "models" / "doc.py").read_text(encoding="utf-8")
    compile(source, "doc.py", "exec")
    # ARRAY 是通用类型（在 PostgreSQL 上渲染成 TEXT[]），INET/JSONB 来自 postgresql 方言
    assert "from sqlalchemy.dialects.postgresql import INET, JSONB" in source
    assert "from sqlalchemy import ARRAY" in source
    assert "payload = Column(JSONB" in source
    assert "tags = Column(ARRAY(Text)" in source


def test_mysql_types_generate_dialect_imports(tmp_path: Path) -> None:
    (tmp_path / "models.yaml").write_text(
        textwrap.dedent(
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
                    values: [a, b]
            """
        ),
        encoding="utf-8",
    )
    _generate(tmp_path)
    source = (tmp_path / "models" / "doc.py").read_text(encoding="utf-8")
    compile(source, "doc.py", "exec")
    assert "from sqlalchemy.dialects.mysql import LONGTEXT, SET" in source
    assert "body = Column(LONGTEXT" in source
    assert "flags = Column(SET('a', 'b')" in source


def test_index_dialect_arguments_are_rendered(tmp_path: Path) -> None:
    (tmp_path / "models.yaml").write_text(
        textwrap.dedent(
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
            """
        ),
        encoding="utf-8",
    )
    _generate(tmp_path)
    source = (tmp_path / "models" / "doc.py").read_text(encoding="utf-8")
    compile(source, "doc.py", "exec")
    assert "postgresql_using='gin'" in source
    assert "postgresql_ops={'payload': 'jsonb_path_ops'}" in source
    assert "postgresql_where=text('deleted_at IS NULL')" in source
    # where 用到了 text()，必须一并导入
    assert "text" in source.split("from .base import Base")[0]


def test_mysql_index_arguments_are_rendered(tmp_path: Path) -> None:
    (tmp_path / "models.yaml").write_text(
        textwrap.dedent(
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
            """
        ),
        encoding="utf-8",
    )
    _generate(tmp_path)
    source = (tmp_path / "models" / "doc.py").read_text(encoding="utf-8")
    compile(source, "doc.py", "exec")
    assert "mysql_prefix='FULLTEXT'" in source
    assert "mysql_length={'url': 191}" in source


def test_generated_package_is_importable_with_dialect_types(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """compile() 只验证语法；这里真的把生成的包导入进来。

    ARRAY(Text) 这类嵌套类型曾经漏生成 ``Text`` 的 import ——
    只有真正 import 才会暴露 NameError。
    """
    package_name = "genpkg_" + uuid.uuid4().hex[:8]
    (tmp_path / "models.yaml").write_text(
        textwrap.dedent(
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
                    type: pg.ARRAY
                    item_type: Text
                  - name: state
                    type: Enum
                    values: [draft, published]
                  - name: seen_at
                    type: pg.TIMESTAMP
                    timezone: true
                  - name: bits
                    type: varbit(8)
            """
        ),
        encoding="utf-8",
    )

    config = load_config(tmp_path / "models.yaml")
    generate_models(
        config, tmp_path / package_name, project_root=tmp_path, backup=False
    )

    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    module = importlib.import_module(package_name)
    try:
        table = module.Doc.__table__
        from sqlalchemy.dialects import postgresql

        assert isinstance(table.c.payload.type, postgresql.JSONB)
        assert isinstance(table.c.tags.type, postgresql.ARRAY)
        assert isinstance(table.c.tags.type.item_type, sa.Text)
        assert isinstance(table.c.state.type, sa.Enum)
        assert isinstance(table.c.bits.type, postgresql.BIT)
        assert table.c.bits.type.varying is True
        assert table.c.seen_at.type.timezone is True
    finally:
        for name in list(sys.modules):
            if name == package_name or name.startswith(f"{package_name}."):
                sys.modules.pop(name, None)


# ── 几何 / DOMAIN / 表达式索引 / UNLOGGED 的生成结果 ─────────────────


def test_spatial_types_generate_helper_module(tmp_path: Path, monkeypatch) -> None:
    package_name = "genpkg_" + uuid.uuid4().hex[:8]
    (tmp_path / "models.yaml").write_text(
        textwrap.dedent(
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
                  - name: shape
                    type: pg.POLYGON
            """
        ),
        encoding="utf-8",
    )

    config = load_config(tmp_path / "models.yaml")
    generate_models(config, tmp_path / package_name, project_root=tmp_path, backup=False)

    helper = tmp_path / package_name / "_gefjon_types.py"
    assert helper.is_file()
    helper_source = helper.read_text(encoding="utf-8")
    assert "class POINT(_GefjonNamedType):" in helper_source
    assert "class POLYGON(_GefjonNamedType):" in helper_source

    source = (tmp_path / package_name / "place.py").read_text(encoding="utf-8")
    compile(source, "place.py", "exec")
    assert "from ._gefjon_types import POINT, POLYGON" in source

    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    module = importlib.import_module(package_name)
    try:
        from sqlalchemy.dialects import postgresql

        ddl = sa.schema.CreateTable(module.Place.__table__).compile(
            dialect=postgresql.dialect()
        ).string
        assert "location POINT" in ddl
        assert "shape POLYGON" in ddl
    finally:
        for name in list(sys.modules):
            if name == package_name or name.startswith(f"{package_name}."):
                sys.modules.pop(name, None)


def test_domain_field_generation(tmp_path: Path) -> None:
    (tmp_path / "models.yaml").write_text(
        textwrap.dedent(
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
            """
        ),
        encoding="utf-8",
    )
    _generate(tmp_path)
    source = (tmp_path / "models" / "person.py").read_text(encoding="utf-8")
    compile(source, "person.py", "exec")
    assert "from sqlalchemy.dialects.postgresql import DOMAIN" in source
    assert "DOMAIN('us_postal_code', String(5), not_null=True)" in source


def test_expression_index_and_concurrently_rendered(tmp_path: Path) -> None:
    (tmp_path / "models.yaml").write_text(
        textwrap.dedent(
            """
            database:
              dialect: postgresql
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
                    concurrently: true
            """
        ),
        encoding="utf-8",
    )
    _generate(tmp_path)
    source = (tmp_path / "models" / "user.py").read_text(encoding="utf-8")
    compile(source, "user.py", "exec")
    assert "text('lower(email)')" in source
    assert "postgresql_concurrently=True" in source
    assert "from sqlalchemy import Column, Index, Integer, String, text" in source


def test_unlogged_emits_event_listener(tmp_path: Path) -> None:
    (tmp_path / "models.yaml").write_text(
        textwrap.dedent(
            """
            database:
              dialect: postgresql
            models:
              - name: Event
                table: events
                unlogged: true
                fields:
                  - name: id
                    type: Integer
                    primary_key: true
            """
        ),
        encoding="utf-8",
    )
    _generate(tmp_path)
    source = (tmp_path / "models" / "event.py").read_text(encoding="utf-8")
    compile(source, "event.py", "exec")
    header = source.split("from .base import Base")[0]
    assert "event" in header
    assert "text" in header
    assert 'event.listens_for(Event.__table__, "after_create")' in source
    assert 'ALTER TABLE {target.name} SET UNLOGGED' in source
