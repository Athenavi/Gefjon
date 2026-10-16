"""``gefjon generate`` —— 根据 models.yaml 生成 ORM 模型代码。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from ..config import DEFAULT_OUTPUT_DIR, load_config
from ..errors import GefjonError
from ..generator import generate_models
from ..project import locate_config
from ..project import project_root as resolve_project_root


def generate(
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help=f"模型包输出目录（默认 ./{DEFAULT_OUTPUT_DIR}）"
    ),
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="models.yaml 路径（默认在当前目录查找）"
    ),
    model: Optional[list[str]] = typer.Option(
        None, "--model", "-m", help="只生成指定模型，可重复传入"
    ),
    backup: bool = typer.Option(
        True, "--backup/--no-backup", help="覆盖前备份现有输出目录"
    ),
) -> None:
    """根据 models.yaml 生成 SQLAlchemy ORM 模型代码。"""
    try:
        config_path = locate_config(config)
        root = resolve_project_root(config_path)
        gefjon_config = load_config(config_path)
        target = output or root / DEFAULT_OUTPUT_DIR
        result = generate_models(
            gefjon_config,
            target,
            project_root=root,
            selected=model or None,
            backup=backup,
        )
    except GefjonError as exc:
        typer.secho(f"错误：{exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    for generated in result.files:
        typer.echo(f"  - {generated.model} -> {generated.path}")
    if result.backup_dir is not None:
        typer.echo(f"  备份：{result.backup_dir}")
    typer.secho(
        f"已生成 {len(result.files)} 个模型文件：{result.output_dir}",
        fg=typer.colors.GREEN,
    )
