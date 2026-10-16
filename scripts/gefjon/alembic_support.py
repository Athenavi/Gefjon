"""Alembic 集成：构建配置、读取迁移状态、运行迁移命令。

所有路径都从 alembic.ini 出发（``script_location = %(here)s``），
不依赖当前工作目录。
"""

from __future__ import annotations

import importlib
import sys
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


# ── 迁移预览（--dry-run）─────────────────────────────────────────────


def _prepare_import_path(project_root: Path) -> None:
    """让**当前项目**的模型包优先被导入。

    把项目根放到 ``sys.path`` 最前面。同一个进程里可能多次调用（测试、批量操作），
    而不同项目的模型包名往往相同，若只是 append，``import models`` 会命中
    ``sys.path`` 里更早的旧项目路径。
    """
    path_str = str(project_root)
    if path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)


def load_target_metadata(alembic_config: AlembicConfig, project_root: Path):
    """按 alembic.ini 的 [gefjon] models_package 导入模型包的 Base.metadata。

    每次都先清掉已缓存的同名包（含子模块），否则同一进程内二次调用会拿到
    上一次导入的旧 metadata。
    """
    package = alembic_config.get_main_option("models_package") or "models"
    _prepare_import_path(project_root)
    for name in list(sys.modules):
        if name == package or name.startswith(f"{package}."):
            del sys.modules[name]
    importlib.invalidate_caches()

    try:
        module = importlib.import_module(package)
    except ImportError as exc:
        raise MigrationError(
            f"无法导入模型包 {package!r}：{exc}；请先运行 `gefjon generate`"
        ) from exc

    base = getattr(module, "Base", None)
    if base is None:
        raise MigrationError(
            f"模型包 {package!r} 没有导出 Base；先运行 `gefjon generate` 重新生成"
        )
    return base.metadata


def _format_diff(item: tuple) -> str:
    """把 ``compare_metadata`` 的一条结果格式化成人能读的一行。"""
    kind = item[0]

    if kind in ("add_table", "remove_table"):
        table = item[1]
        return f"{'+' if kind == 'add_table' else '-'} 表 {table.name}"

    if kind in ("add_column", "remove_column"):
        _, _schema, table_name, column = item[:4]
        return (
            f"  {'+' if kind == 'add_column' else '-'} 列 "
            f"{table_name}.{column.name} ({column.type})"
        )

    if kind == "modify_type":
        _, _schema, table_name, column_name, existing, target = item[:6]
        return f"  ~ 列 {table_name}.{column_name} 类型 {existing} -> {target}"

    if kind in ("add_index", "remove_index"):
        index = item[1]
        table_name = getattr(getattr(index, "table", None), "name", "?")
        return (
            f"  {'+' if kind == 'add_index' else '-'} 索引 "
            f"{index.name}（表 {table_name}）"
        )

    if kind in ("add_constraint", "remove_constraint"):
        constraint = item[1]
        table_name = getattr(getattr(constraint, "table", None), "name", "?")
        name = getattr(constraint, "name", "?")
        return (
            f"  {'+' if kind == 'add_constraint' else '-'} 约束 "
            f"{name}（表 {table_name}）"
        )

    return f"  ? {kind}: {item[1:]!r}"


def preview_changes(
    project_root: Path, project: GefjonConfig
) -> tuple[str, ...]:
    """比较模型与数据库，返回将要应用的变更摘要。

    只读：不生成脚本、不执行任何 DDL。
    """
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    alembic_config = build_config(project_root, project.migration.directory)
    ensure_database_url(alembic_config, project)
    metadata = load_target_metadata(alembic_config, project_root)

    database_url = resolve_database_url(
        ini_url=ini_database_url(alembic_config), project_root=project_root
    )

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"compare_type": True}
            )
            differences = compare_metadata(context, metadata)
    except Exception as exc:
        raise MigrationError(f"对比模型与数据库失败：{exc}") from exc
    finally:
        engine.dispose()

    return tuple(_format_diff(item) for item in differences)
