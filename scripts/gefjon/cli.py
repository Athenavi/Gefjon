"""Gefjon 命令行入口。"""

from __future__ import annotations

import typer

from . import __version__
from .commands import generate as generate_command
from .commands import init as init_command
from .commands import migrate as migrate_command
from .commands import shell as shell_command
from .commands import status as status_command

app = typer.Typer(
    name="gefjon",
    help="基于 YAML 配置生成 SQLAlchemy ORM 模型，并用 Alembic 完成数据库迁移。",
    add_completion=False,
    rich_markup_mode="rich",
    no_args_is_help=True,
)

app.command("generate", help="根据 models.yaml 生成 ORM 模型代码")(generate_command.generate)
app.command("migrate", help="生成迁移脚本（默认只生成，不执行）")(migrate_command.migrate)
app.command("upgrade", help="应用迁移到指定 revision")(migrate_command.upgrade)
app.command("downgrade", help="回滚到指定 revision")(migrate_command.downgrade)
app.command("history", help="显示迁移历史")(migrate_command.history)
app.command("status", help="显示版本映射与迁移状态")(status_command.status)
app.command("init", help="初始化 Gefjon 项目结构")(init_command.init)
app.command("shell", help="启动预加载上下文的交互式 shell")(shell_command.shell)


@app.command("version", help="显示 Gefjon 版本")
def version() -> None:
    """显示 Gefjon 版本。"""
    typer.echo(f"gefjon {__version__}")


def main() -> None:
    """console_scripts 入口。"""
    app()


if __name__ == "__main__":
    main()
