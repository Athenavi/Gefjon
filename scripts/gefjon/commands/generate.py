"""``gefjon generate`` —— 根据 models.yaml 生成 ORM 模型代码。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from ..config import DEFAULT_OUTPUT_DIR, GefjonConfig, load_config
from ..errors import GefjonError
from ..generator import check_models, generate_models
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
    check: bool = typer.Option(
        False, "--check", help="只校验模型包是否与 models.yaml 一致，不写任何文件"
    ),
) -> None:
    """根据 models.yaml 生成 SQLAlchemy ORM 模型代码。

    加上 ``--check`` 时只做校验：模型包与 models.yaml 不一致就以非零退出码结束。
    适合放进 CI，防止忘记重新生成、或有人直接手改生成出来的文件。
    """
    try:
        config_path = locate_config(config)
        root = resolve_project_root(config_path)
        gefjon_config = load_config(config_path)
        target = output or root / DEFAULT_OUTPUT_DIR

        if check:
            _run_check(gefjon_config, target, model or None)
            return

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


def _run_check(
    gefjon_config: GefjonConfig, target: Path, selected: list[str] | None
) -> None:
    """``--check`` 的实现：一致就返回，否则列出差异并以 1 退出。"""
    result = check_models(gefjon_config, target, selected=selected)
    if result.ok:
        typer.secho(f"模型包与 models.yaml 一致：{target}", fg=typer.colors.GREEN)
        return

    for path in result.missing:
        typer.echo(f"  缺失：{path}")
    for path in result.changed:
        typer.echo(f"  不一致：{path}")
    for path in result.extra:
        typer.echo(f"  多余：{path}")
    typer.secho(
        "模型包与 models.yaml 不一致，请运行 `gefjon generate`",
        err=True,
        fg=typer.colors.RED,
    )
    raise typer.Exit(code=1)
