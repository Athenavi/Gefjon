"""CLI 端到端：init -> generate -> migrate -> upgrade -> status。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gefjon.cli import app

runner = CliRunner()


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_version(workdir: Path) -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "gefjon" in result.output


def test_help_lists_documented_commands(workdir: Path) -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in (
        "generate",
        "migrate",
        "upgrade",
        "downgrade",
        "status",
        "history",
        "init",
    ):
        assert command in result.output


def test_init_creates_scaffold(workdir: Path) -> None:
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output

    migrations = workdir / "migrations"
    assert (migrations / "alembic.ini").is_file()
    assert (migrations / "env.py").is_file()
    assert (migrations / "script.py.mako").is_file()
    assert (migrations / "versions").is_dir()
    assert (workdir / "models.yaml").is_file()


def test_init_is_idempotent_without_force(workdir: Path) -> None:
    runner.invoke(app, ["init"])
    marker = workdir / "migrations" / "env.py"
    marker.write_text("# 用户修改\n", encoding="utf-8")

    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert marker.read_text(encoding="utf-8") == "# 用户修改\n"
    assert "已存在，跳过" in result.output


def test_generate_requires_config(workdir: Path) -> None:
    result = runner.invoke(app, ["generate"])
    assert result.exit_code == 1
    assert "models.yaml" in result.output


def test_full_flow(workdir: Path) -> None:
    assert runner.invoke(app, ["init"]).exit_code == 0

    generated = runner.invoke(app, ["generate"])
    assert generated.exit_code == 0, generated.output
    assert (workdir / "models" / "user.py").is_file()
    assert (workdir / "models" / "post.py").is_file()

    revised = runner.invoke(app, ["migrate", "--message", "initial schema"])
    assert revised.exit_code == 0, revised.output
    versions = list((workdir / "migrations" / "versions").glob("*.py"))
    assert versions, "应生成迁移脚本"

    upgraded = runner.invoke(app, ["upgrade"])
    assert upgraded.exit_code == 0, upgraded.output

    status = runner.invoke(app, ["status"])
    assert status.exit_code == 0, status.output
    assert "当前 DB revision" in status.output
    assert "待应用的迁移：无" in status.output

    assert (workdir / ".gefjon" / "version_map.json").is_file()

    # 数据库里确实建出了表
    database = workdir / "app.db"
    assert database.is_file()
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert {"users", "posts", "alembic_version"} <= tables


def test_migrate_writes_backup(workdir: Path) -> None:
    runner.invoke(app, ["init"])
    runner.invoke(app, ["generate"])
    result = runner.invoke(app, ["migrate", "--message", "first"])
    assert result.exit_code == 0, result.output

    backups = list((workdir / ".gefjon" / "backups").glob("*"))
    assert backups, "迁移前应产生备份目录"


def test_generate_exit_code_on_bad_config(workdir: Path) -> None:
    (workdir / "models.yaml").write_text(
        "models:\n  - name: Thing\n    fields:\n      - name: 'x; import os'\n        type: Integer\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["generate"])
    assert result.exit_code == 1


def test_status_without_ini_fails_clearly(workdir: Path) -> None:
    (workdir / "models.yaml").write_text("models: []\n", encoding="utf-8")
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 1
    assert "alembic.ini" in result.output


def test_shell_exposes_options_not_preempting_subcommands(workdir: Path) -> None:
    """旧实现的 callback 会抢在 `shell ipython` 之前进入标准 shell。

    现在是单一命令 + 选项，结构上不存在“默认 shell 抢占子命令”的问题。
    """
    result = runner.invoke(app, ["shell", "--help"])
    assert result.exit_code == 0, result.output
    assert "--ipython" in result.output
    assert "--models-package" in result.output


def test_init_then_generate_does_not_touch_source(workdir: Path) -> None:
    """generate 只写输出目录，不会在仓库里散落其它文件。"""
    runner.invoke(app, ["init"])
    runner.invoke(app, ["generate"])
    assert (workdir / "models").is_dir()
    assert not (workdir / "configs").exists()
    assert not (workdir / "scripts").exists()


# ── generate --check（漂移检测）───────────────────────────────────────


def test_generate_check_passes_after_generate(workdir: Path) -> None:
    runner.invoke(app, ["init"])
    runner.invoke(app, ["generate"])
    result = runner.invoke(app, ["generate", "--check"])
    assert result.exit_code == 0, result.output
    assert "一致" in result.output


def test_generate_is_deterministic(workdir: Path) -> None:
    """连续两次生成的产物必须逐字一致，否则 --check 没有意义。"""
    runner.invoke(app, ["init"])
    runner.invoke(app, ["generate"])
    models = workdir / "models"
    first = {
        path.relative_to(models): path.read_text(encoding="utf-8")
        for path in sorted(models.rglob("*.py"))
    }

    runner.invoke(app, ["generate"])
    second = {
        path.relative_to(models): path.read_text(encoding="utf-8")
        for path in sorted(models.rglob("*.py"))
    }
    assert first == second


def test_generate_check_detects_missing_output(workdir: Path) -> None:
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["generate", "--check"])
    assert result.exit_code == 1
    assert "缺失" in result.output


def test_generate_check_detects_manual_edit(workdir: Path) -> None:
    runner.invoke(app, ["init"])
    runner.invoke(app, ["generate"])
    user_py = workdir / "models" / "user.py"
    user_py.write_text(
        user_py.read_text(encoding="utf-8") + "\n# 被人手动改过\n", encoding="utf-8"
    )

    result = runner.invoke(app, ["generate", "--check"])
    assert result.exit_code == 1
    assert "不一致" in result.output
    # --check 是只读的：不能把文件改回去
    assert "# 被人手动改过" in user_py.read_text(encoding="utf-8")


def test_generate_check_detects_stale_config(workdir: Path) -> None:
    """改了 models.yaml 却没重新生成。"""
    runner.invoke(app, ["init"])
    runner.invoke(app, ["generate"])
    config_path = workdir / "models.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("String(50)", "String(80)"),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["generate", "--check"])
    assert result.exit_code == 1
    assert "不一致" in result.output


def test_generate_check_detects_orphan_file(workdir: Path) -> None:
    runner.invoke(app, ["init"])
    runner.invoke(app, ["generate"])
    (workdir / "models" / "orphan.py").write_text("# 孤儿文件\n", encoding="utf-8")

    result = runner.invoke(app, ["generate", "--check"])
    assert result.exit_code == 1
    assert "多余" in result.output


# ── migrate --dry-run（迁移预览）─────────────────────────────────────


def test_migrate_dry_run_lists_changes(workdir: Path) -> None:
    runner.invoke(app, ["init"])
    runner.invoke(app, ["generate"])

    result = runner.invoke(app, ["migrate", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "将要应用的 schema 变更" in result.output
    assert "+ 表 users" in result.output
    assert "+ 表 posts" in result.output
    # 只读：不能生成迁移脚本
    assert list((workdir / "migrations" / "versions").glob("*.py")) == []


def test_migrate_dry_run_reports_no_changes_when_in_sync(workdir: Path) -> None:
    runner.invoke(app, ["init"])
    runner.invoke(app, ["generate"])
    runner.invoke(app, ["migrate", "-m", "initial"])
    runner.invoke(app, ["upgrade"])

    result = runner.invoke(app, ["migrate", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "没有待应用的 schema 变更" in result.output


def test_migrate_dry_run_detects_new_column(workdir: Path) -> None:
    runner.invoke(app, ["init"])
    runner.invoke(app, ["generate"])
    runner.invoke(app, ["migrate", "-m", "initial"])
    runner.invoke(app, ["upgrade"])

    config_path = workdir / "models.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "      - name: published_at\n        type: DateTime\n        nullable: true\n",
            "      - name: published_at\n"
            "        type: DateTime\n"
            "        nullable: true\n"
            "      - name: views\n"
            "        type: Integer\n"
            "        nullable: false\n"
            "        default: 0\n",
        ),
        encoding="utf-8",
    )
    runner.invoke(app, ["generate"])

    result = runner.invoke(app, ["migrate", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "views" in result.output
