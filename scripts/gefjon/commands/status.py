"""``gefjon status`` —— 显示版本映射与迁移状态。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from ..alembic_support import build_config, ensure_database_url, read_state
from ..config import load_config
from ..database import safe_url
from ..errors import GefjonError
from ..mapping import load_version_map
from ..project import locate_config
from ..project import project_root as resolve_project_root


def status(
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="models.yaml 路径（默认在当前目录查找）"
    ),
) -> None:
    """显示项目版本、数据库 revision 与待应用的迁移。"""
    try:
        config_path = locate_config(config)
        root = resolve_project_root(config_path)
        gefjon_config = load_config(config_path)
        alembic_config = build_config(root, gefjon_config.migration.directory)
        ensure_database_url(alembic_config, gefjon_config)
        state = read_state(root, alembic_config)
    except GefjonError as exc:
        typer.secho(f"错误：{exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.echo(f"项目版本：{gefjon_config.project.version}")
    typer.echo(f"数据库：{safe_url(state.database_url)}")
    typer.echo(f"当前 DB revision：{state.current_revision or '(未初始化)'}")
    typer.echo(f"最新 revision：{state.head_revision or '(无)'}")

    if state.database_error is not None:
        typer.secho(f"警告：{state.database_error}", fg=typer.colors.YELLOW)
    elif state.pending:
        typer.echo("待应用的迁移：")
        for revision, doc in state.pending:
            typer.echo(f"  - {revision[:12]}: {doc}")
    else:
        typer.echo("待应用的迁移：无")

    version_map = load_version_map(root)
    if version_map is not None:
        typer.echo(
            "版本映射缓存："
            f" project_version={version_map.project_version or '-'}"
            f" db_revision={version_map.db_revision or '-'}"
            f" updated_at={version_map.updated_at or '-'}"
        )

    if gefjon_config.third_party:
        typer.echo("第三方项目映射：")
        for mapping in gefjon_config.third_party:
            typer.echo(
                f"  - {mapping.project} {mapping.version} -> {mapping.db_revision}"
            )
