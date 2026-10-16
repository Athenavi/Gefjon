"""Alembic 运行环境 —— 由 Gefjon 生成，可自由修改。

数据库连接串按下面的顺序解析（**fail-closed**）：

1. ``DATABASE_DSN`` 环境变量
2. ``data/install.lock``（AES-256-GCM + scrypt，需要 ``APP_SECRET``）
3. ``alembic.ini`` 的 ``sqlalchemy.url``

只要 ``install.lock`` 存在却无法解密，这里就直接报错，绝不静默回退到
其它连接串 —— 否则迁移可能被打到另一个数据库上。

注意：本文件里的运行时输出（print / 异常消息）保持 ASCII，因为
Windows 控制台的默认编码不一定是 UTF-8。
"""

from __future__ import annotations

import importlib
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

project_root = Path(__file__).resolve().parent.parent

# 可选：加载 .env（不覆盖已有环境变量）
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    for candidate in (project_root / ".env", project_root / "config" / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)
            break

# 让项目根可被导入；追加到末尾，避免遮蔽标准库或第三方包
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

# ── 连接串 ────────────────────────────────────────────────────────────
try:
    from gefjon.database import resolve_database_url, safe_url
except ImportError:  # 允许在未安装 gefjon 的环境里仅使用 alembic.ini
    def resolve_database_url(*, ini_url, project_root):  # type: ignore[misc]
        if not ini_url:
            raise RuntimeError(
                "gefjon is not installed and alembic.ini has no sqlalchemy.url; "
                "cannot determine the database"
            )
        return ini_url

    def safe_url(url):  # type: ignore[misc]
        return "(credentials hidden)"

db_url = resolve_database_url(
    ini_url=config.get_main_option("sqlalchemy.url"), project_root=project_root
)
config.set_main_option("sqlalchemy.url", db_url)
print(f"[alembic] database: {safe_url(db_url)}")

# ── 模型元数据 ────────────────────────────────────────────────────────
# 由 `gefjon generate` 生成的包负责导出 Base 与全部模型类。
models_package = config.get_main_option("models_package") or "models"
try:
    models_module = importlib.import_module(models_package)
except ImportError as exc:
    raise RuntimeError(
        f"cannot import model package {models_package!r}: {exc}\n"
        "Run `gefjon generate` first; if the package name differs, set "
        "[gefjon] models_package in alembic.ini."
    ) from exc

Base = getattr(models_module, "Base", None)
if Base is None:
    raise RuntimeError(
        f"model package {models_package!r} does not export Base; "
        "run `gefjon generate` to regenerate it."
    )

target_metadata = Base.metadata

#: 是否把其它 schema 也纳入 autogenerate 比对（默认关闭，避免误判）
include_schemas = (config.get_main_option("include_schemas") or "").lower() in {
    "1",
    "true",
    "yes",
}


def run_migrations_offline() -> None:
    """离线模式：只输出 SQL，不连接数据库。"""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_schemas=include_schemas,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：建立连接并执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # batch 模式会重建表，只有 SQLite 需要；对 PostgreSQL/MySQL 使用
        # batch 会引入不必要的重建风险，所以按方言开启。
        is_sqlite = connection.dialect.name == "sqlite"
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=is_sqlite,
            include_schemas=include_schemas,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
