"""Alembic 集成：构建配置、读取迁移状态、运行迁移命令。

所有路径都从 alembic.ini 出发（``script_location = %(here)s``），
不依赖当前工作目录。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from .config import GefjonConfig
from .database import resolve_database_url
from .errors import ConfigError, MigrationError
from .project import locate_alembic_ini


@dataclass(frozen=True)
class MigrationState:
    """当前迁移状态。"""

    database_url: str | None
    current_revision: str | None
    head_revision: str | None
    pending: tuple[tuple[str, str], ...]
    history: tuple[tuple[str, str], ...]
    database_error: str | None = None


def build_config(project_root: Path, migration_dir: str) -> AlembicConfig:
    """定位并加载 alembic.ini。"""
    ini_path = locate_alembic_ini(project_root, migration_dir)
    if ini_path is None:
        raise MigrationError(
            "找不到 alembic.ini；请先运行 `gefjon init` 初始化迁移目录"
        )
    return AlembicConfig(str(ini_path))


def ini_database_url(config: AlembicConfig) -> str | None:
    """读取 alembic.ini 中的 sqlalchemy.url（可能为空）。"""
    url = config.get_main_option("sqlalchemy.url")
    return url or None


def ensure_database_url(config: AlembicConfig, project: GefjonConfig) -> None:
    """alembic.ini 没有连接串时，用 models.yaml 的 database.url 兜底。

    设置的 Config 对象会原样传进 env.py（``context.config``），所以
    env.py 也能读到这个兜底值。
    """
    if not (config.get_main_option("sqlalchemy.url") or "").strip() and project.database.url:
        config.set_main_option("sqlalchemy.url", project.database.url)


def connect(database_url: str):
    """建立数据库连接（NullPool，短连接）。"""
    engine = create_engine(database_url, poolclass=NullPool)
    return engine.connect()


def read_state(project_root: Path, alembic_config: AlembicConfig) -> MigrationState:
    """读取当前 revision、head 与待应用的迁移。"""
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(alembic_config)
    head = script.get_current_head()
    history = tuple(
        (revision.revision, revision.doc or "")
        for revision in script.walk_revisions()
    )

    database_url: str | None = None
    database_error: str | None = None
    try:
        database_url = resolve_database_url(
            ini_url=ini_database_url(alembic_config), project_root=project_root
        )
    except ConfigError as exc:
        database_error = str(exc)

    current: str | None = None
    if database_url:
        try:
            connection = connect(database_url)
            try:
                current = MigrationContext.configure(connection).get_current_revision()
            finally:
                connection.close()
        except Exception as exc:
            database_error = f"无法连接数据库：{exc}"

    pending: tuple[tuple[str, str], ...] = ()
    if database_error is None:
        pending = _pending_revisions(script, current)

    return MigrationState(
        database_url=database_url,
        current_revision=current,
        head_revision=head,
        pending=pending,
        history=history,
        database_error=database_error,
    )


def _pending_revisions(script, current: str | None) -> tuple[tuple[str, str], ...]:
    """返回 current 之后、head 之前的迁移（head 在前）。"""
    if current == script.get_current_head():
        return ()

    pending: list[tuple[str, str]] = []
    for revision in script.walk_revisions(base=current or "base", head="head"):
        if revision.revision == current:
            continue
        pending.append((revision.revision, revision.doc or ""))
    return tuple(pending)


def run_revision(config: AlembicConfig, *, message: str | None, autogenerate: bool) -> None:
    """生成一个新的迁移脚本。"""
    from alembic import command

    try:
        command.revision(
            config,
            message=message or "gefjon migration",
            autogenerate=autogenerate,
        )
    except Exception as exc:
        raise MigrationError(f"生成迁移脚本失败：{exc}") from exc


def run_upgrade(config: AlembicConfig, revision: str) -> None:
    from alembic import command

    try:
        command.upgrade(config, revision)
    except Exception as exc:
        raise MigrationError(f"执行迁移失败：{exc}") from exc


def run_downgrade(config: AlembicConfig, revision: str) -> None:
    from alembic import command

    try:
        command.downgrade(config, revision)
    except Exception as exc:
        raise MigrationError(f"回滚失败：{exc}") from exc


def print_history(config: AlembicConfig) -> None:
    from alembic import command

    try:
        command.history(config)
    except Exception as exc:
        raise MigrationError(f"读取迁移历史失败：{exc}") from exc
