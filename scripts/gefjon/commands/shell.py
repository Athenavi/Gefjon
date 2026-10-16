"""``gefjon shell`` —— 预加载 Gefjon 上下文的交互式 shell。

与旧实现的区别：不再无条件抢占子命令（那个 callback 会让
``shell ipython`` 永远进不去），也不再硬编码任何宿主的应用工厂。
"""

from __future__ import annotations

import code
import importlib
from pathlib import Path
from typing import Optional

import typer

from ..config import load_config
from ..errors import GefjonError
from ..project import locate_config
from ..project import project_root as resolve_project_root


def _build_namespace(config: Optional[Path], models_package: str) -> dict:
    namespace: dict = {}

    try:
        config_path = locate_config(config)
        gefjon_config = load_config(config_path)
        namespace["config"] = gefjon_config
        namespace["project_root"] = resolve_project_root(config_path)
        typer.echo(f"  已导入: config, project_root（{config_path}）")
    except GefjonError as exc:
        typer.secho(f"  提示: 未加载 models.yaml（{exc}）", fg=typer.colors.YELLOW)

    try:
        module = importlib.import_module(models_package)
        namespace[models_package] = module
        base = getattr(module, "Base", None)
        if base is not None:
            namespace["Base"] = base
        typer.echo(f"  已导入: {models_package}")
    except Exception as exc:
        typer.secho(f"  提示: 未加载模型包 {models_package}（{exc}）", fg=typer.colors.YELLOW)

    return namespace


def shell(
    models_package: str = typer.Option(
        "models", "--models-package", help="要预加载的模型包名"
    ),
    ipython: bool = typer.Option(False, "--ipython", help="优先使用 IPython"),
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="models.yaml 路径（默认在当前目录查找）"
    ),
) -> None:
    """启动交互式 shell（预加载配置与模型包）。"""
    namespace = _build_namespace(config, models_package)

    if ipython:
        try:
            from IPython import start_ipython

            start_ipython(argv=[], user_ns=namespace)
            return
        except ImportError:
            typer.echo("IPython 未安装，回退到标准 Python shell")

    typer.echo("启动 Python shell...")
    code.interact(local=namespace, banner="")
