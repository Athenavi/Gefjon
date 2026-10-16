"""定位项目中的配置文件与 Alembic 配置。

所有路径都以“配置文件所在目录”为项目根，避免依赖当前工作目录 ——
旧实现里硬编码的 ``Path(__file__).parent.parent`` 与 CWD 相对路径
正是生成器与迁移命令互相找不到文件的根因。
"""

from __future__ import annotations

from pathlib import Path

from .config import DEFAULT_MIGRATIONS_DIR
from .errors import ConfigError

#: 依次尝试的配置文件名
CONFIG_FILENAMES = ("models.yaml", "models.yml")


def locate_config(explicit: Path | None = None) -> Path:
    """找到 models.yaml。"""
    if explicit is not None:
        if not explicit.exists():
            raise ConfigError(f"指定的配置文件不存在：{explicit}")
        return explicit

    for name in CONFIG_FILENAMES:
        candidate = Path.cwd() / name
        if candidate.exists():
            return candidate

    raise ConfigError(
        "当前目录下找不到 models.yaml；用 --config 指定路径，或先运行 `gefjon init`"
    )


def project_root(config_path: Path) -> Path:
    """项目根目录 = 配置文件所在目录。"""
    return config_path.resolve().parent


def locate_alembic_ini(
    root: Path, migration_dir: str = DEFAULT_MIGRATIONS_DIR
) -> Path | None:
    """找到 alembic.ini：优先 migrations/ 下，其次项目根。"""
    for candidate in (root / migration_dir / "alembic.ini", root / "alembic.ini"):
        if candidate.exists():
            return candidate
    return None
