"""``gefjon migrate`` / ``upgrade`` / ``downgrade`` / ``history``。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from ..alembic_support import (
    build_config,
    ensure_database_url,
    print_history,
    read_state,
    run_downgrade,
    run_revision,
    run_upgrade,
)
from ..backup import backup_before_migration
from ..config import load_config
from ..errors import GefjonError
from ..mapping import VersionMap, load_version_map, save_version_map
from ..project import locate_config
from ..project import project_root as resolve_project_root


def _load_context(config: Optional[Path]):
    """定位配置并构建好（含连接串兜底的）alembic Config。"""
    config_path = locate_config(config)
    root = resolve_project_root(config_path)
    gefjon_config = load_config(config_path)
    alembic_config = build_config(root, gefjon_config.migration.directory)
    ensure_database_url(alembic_config, gefjon_config)
    return root, gefjon_config, alembic_config


def _current_revision(alembic_config, root: Path) -> str | None:
    try:
        return read_state(root, alembic_config).current_revision
    except GefjonError:
        return None


def _do_backup(root: Path, migration_dir: str, current: str | None) -> None:
    result = backup_before_migration(root, root / migration_dir, current)
    if result is not None:
        typer.echo(f"  备份：{result.directory}")


def _record_version_map(root: Path, gefjon_config, revision: str | None) -> None:
    version_map = load_version_map(root) or VersionMap.from_third_party(
        gefjon_config.project.name,
        gefjon_config.project.version,
        gefjon_config.third_party,
    )
    version_map.project_name = gefjon_config.project.name
    version_map.project_version = gefjon_config.project.version
    version_map.db_revision = revision
    if gefjon_config.third_party:
        version_map.third_party = [
            {
                "project": mapping.project,
                "version": mapping.version,
                "db_revision": mapping.db_revision,
            }
            for mapping in gefjon_config.third_party
        ]
    save_version_map(root, version_map)


def migrate(
    message: Optional[str] = typer.Option(
        None, "--message", "-m", "--revision", help="迁移说明（也用作脚本标题）"
    ),
    autogenerate: bool = typer.Option(
        True, "--autogenerate/--no-autogenerate", help="对比模型与数据库自动生成内容"
    ),
    apply: bool = typer.Option(
        False, "--apply/--no-apply", help="生成后立即执行（默认只生成脚本）"
    ),
    backup: bool = typer.Option(
        True, "--backup/--no-backup", help="生成前备份迁移脚本目录"
    ),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="models.yaml 路径"),
) -> None:
    """生成一个新的迁移脚本。"""
    try:
        root, gefjon_config, alembic_config = _load_context(config)
        migration_dir = gefjon_config.migration.directory
        current = _current_revision(alembic_config, root)

        if backup:
            _do_backup(root, migration_dir, current)

        run_revision(alembic_config, message=message, autogenerate=autogenerate)
        typer.secho("迁移脚本已生成", fg=typer.colors.GREEN)

        if apply:
            run_upgrade(alembic_config, "head")
            current = _current_revision(alembic_config, root)
            typer.secho("迁移已应用", fg=typer.colors.GREEN)

        _record_version_map(root, gefjon_config, current)
    except GefjonError as exc:
        typer.secho(f"错误：{exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc


def upgrade(
    revision: str = typer.Argument("head", help="目标 revision（默认 head）"),
    backup: bool = typer.Option(True, "--backup/--no-backup", help="执行前备份迁移脚本"),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="models.yaml 路径"),
) -> None:
    """应用迁移到指定 revision。"""
    try:
        root, gefjon_config, alembic_config = _load_context(config)
        if backup:
            _do_backup(
                root,
                gefjon_config.migration.directory,
                _current_revision(alembic_config, root),
            )

        run_upgrade(alembic_config, revision)
        _record_version_map(
            root, gefjon_config, _current_revision(alembic_config, root)
        )
        typer.secho(f"已应用迁移到 {revision}", fg=typer.colors.GREEN)
    except GefjonError as exc:
        typer.secho(f"错误：{exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc


def downgrade(
    revision: str = typer.Argument("base", help="目标 revision（默认 base）"),
    backup: bool = typer.Option(True, "--backup/--no-backup", help="回滚前备份迁移脚本"),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="models.yaml 路径"),
) -> None:
    """回滚到指定 revision。"""
    try:
        root, gefjon_config, alembic_config = _load_context(config)
        if backup:
            _do_backup(
                root,
                gefjon_config.migration.directory,
                _current_revision(alembic_config, root),
            )

        run_downgrade(alembic_config, revision)
        _record_version_map(
            root, gefjon_config, _current_revision(alembic_config, root)
        )
        typer.secho(f"已回滚到 {revision}", fg=typer.colors.GREEN)
    except GefjonError as exc:
        typer.secho(f"错误：{exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc


def history(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="显示详细信息"),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="models.yaml 路径"),
) -> None:
    """显示迁移历史。"""
    try:
        _, _, alembic_config = _load_context(config)
        print_history(alembic_config)
    except GefjonError as exc:
        typer.secho(f"错误：{exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc


__all__ = ["migrate", "upgrade", "downgrade", "history"]
