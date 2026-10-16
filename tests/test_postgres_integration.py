"""PostgreSQL 集成测试。

默认**跳过**：只有设置了 ``GEFJON_TEST_POSTGRES_DSN``、并且装了 psycopg / psycopg2
时才会真的连库运行。CI 里由 ``.github/workflows/ci.yml`` 的 postgres 服务容器提供。

这里验证的是"只在真实数据库上才成立"的东西：PG 专有类型最终落成什么列类型、
UNLOGGED 是否真的生效、Alembic 版本表是否写入、以及 dry-run 能否发现漂移。
"""

from __future__ import annotations

import importlib.util
import os

import pytest
import sqlalchemy as sa
from typer.testing import CliRunner

from gefjon.cli import app

runner = CliRunner()

DSN = os.environ.get("GEFJON_TEST_POSTGRES_DSN", "").strip()


def _driver_available() -> bool:
    return any(
        importlib.util.find_spec(name) is not None for name in ("psycopg", "psycopg2")
    )


pytestmark = pytest.mark.skipif(
    not DSN or not _driver_available(),
    reason="需要 GEFJON_TEST_POSTGRES_DSN 与 psycopg/psycopg2 才能运行 PostgreSQL 集成测试",
)

MODELS = """database:
  dialect: postgresql

models:
  - name: Doc
    table: docs
    unlogged: true
    description: 文档
    fields:
      - name: id
        type: Integer
        primary_key: true
      - name: payload
        type: JSONB
      - name: tags
        type: pg.ARRAY
        item_type: Text
      - name: addr
        type: INET
      - name: uid
        type: uuid
      - name: seen_at
        type: pg.TIMESTAMP
        timezone: true
      - name: blob
        type: BYTEA
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def engine():
    engine = sa.create_engine(DSN)
    yield engine
    engine.dispose()


def _reset_schema(engine) -> None:
    """清空测试库，保证可重复运行。"""
    with engine.begin() as connection:
        connection.execute(sa.text("DROP SCHEMA public CASCADE"))
        connection.execute(sa.text("CREATE SCHEMA public"))


def test_full_flow_on_postgres(project, engine) -> None:
    _reset_schema(engine)
    (project / "models.yaml").write_text(MODELS, encoding="utf-8")

    assert runner.invoke(app, ["init", "--database-url", DSN]).exit_code == 0

    generated = runner.invoke(app, ["generate"])
    assert generated.exit_code == 0, generated.output

    revised = runner.invoke(app, ["migrate", "-m", "initial schema"])
    assert revised.exit_code == 0, revised.output

    upgraded = runner.invoke(app, ["upgrade"])
    assert upgraded.exit_code == 0, upgraded.output

    with engine.connect() as connection:
        column_types = {
            row.column_name: row.udt_name
            for row in connection.execute(
                sa.text(
                    "SELECT column_name, udt_name FROM information_schema.columns"
                    " WHERE table_name = 'docs'"
                )
            )
        }
        assert column_types["payload"] == "jsonb"
        assert column_types["tags"] == "_text"
        assert column_types["addr"] == "inet"
        assert column_types["uid"] == "uuid"
        assert column_types["seen_at"] == "timestamptz"
        assert column_types["blob"] == "bytea"

        persistence = connection.execute(
            sa.text("SELECT relpersistence FROM pg_class WHERE relname = 'docs'")
        ).scalar()
        assert persistence == "u", "docs 应当是 UNLOGGED 表"

        revision = connection.execute(
            sa.text("SELECT version_num FROM alembic_version")
        ).scalar()
        assert revision

    status = runner.invoke(app, ["status"])
    assert status.exit_code == 0, status.output
    assert "待应用的迁移：无" in status.output


def test_dry_run_detects_drift_on_postgres(project, engine) -> None:
    _reset_schema(engine)
    (project / "models.yaml").write_text(MODELS, encoding="utf-8")

    runner.invoke(app, ["init", "--database-url", DSN])
    runner.invoke(app, ["generate"])
    runner.invoke(app, ["migrate", "-m", "initial"])
    assert runner.invoke(app, ["upgrade"]).exit_code == 0

    in_sync = runner.invoke(app, ["migrate", "--dry-run"])
    assert in_sync.exit_code == 0, in_sync.output
    assert "没有待应用的 schema 变更" in in_sync.output

    (project / "models.yaml").write_text(
        MODELS.replace(
            "      - name: blob",
            "      - name: note\n        type: Text\n        nullable: true\n"
            "      - name: blob",
        ),
        encoding="utf-8",
    )
    runner.invoke(app, ["generate"])

    drifted = runner.invoke(app, ["migrate", "--dry-run"])
    assert drifted.exit_code == 0, drifted.output
    assert "note" in drifted.output


def test_generate_check_on_postgres_project(project, engine) -> None:
    """漂移检测与数据库无关，但顺带确认它在真实项目结构下可用。"""
    _reset_schema(engine)
    (project / "models.yaml").write_text(MODELS, encoding="utf-8")
    runner.invoke(app, ["init", "--database-url", DSN])
    runner.invoke(app, ["generate"])

    assert runner.invoke(app, ["generate", "--check"]).exit_code == 0

    doc_py = project / "models" / "doc.py"
    doc_py.write_text(doc_py.read_text(encoding="utf-8") + "\n# 手改\n", encoding="utf-8")
    assert runner.invoke(app, ["generate", "--check"]).exit_code == 1
