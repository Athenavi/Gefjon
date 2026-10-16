"""迁移前备份。

备份的是**迁移脚本目录与当前数据库 revision**，落到
``<project_root>/.gefjon/backups/<timestamp>/``。这样任何一次迁移都可以
从备份中找回当时的迁移脚本，并知道回滚目标 revision。

数据库数据的物理备份依赖具体数据库的导出工具，不在本工具的职责内，
README 对此有如实说明。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

BACKUPS_DIRNAME = "backups"


@dataclass(frozen=True)
class MigrationBackup:
    directory: Path
    revision: str | None
    copied_files: tuple[Path, ...]


def backup_before_migration(
    project_root: Path,
    migrations_dir: Path,
    current_revision: str | None,
) -> MigrationBackup | None:
    """备份迁移脚本目录并记录当前 revision。

    Returns:
        备份信息；当没有任何可备份内容时返回 ``None``。
    """
    versions_dir = migrations_dir / "versions"
    copied: list[Path] = []

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    target = project_root / ".gefjon" / BACKUPS_DIRNAME / stamp
    counter = 1
    while target.exists():
        counter += 1
        target = project_root / ".gefjon" / BACKUPS_DIRNAME / f"{stamp}-{counter}"

    if versions_dir.exists():
        for source in sorted(versions_dir.glob("*.py")):
            destination = target / "versions" / source.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied.append(destination)

    alembic_ini = migrations_dir / "alembic.ini"
    if alembic_ini.exists():
        destination = target / "alembic.ini"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(alembic_ini, destination)
        copied.append(destination)

    if not copied and current_revision is None:
        return None

    target.mkdir(parents=True, exist_ok=True)
    (target / "revision.txt").write_text(
        f"revision={current_revision or ''}\n"
        f"created_at={datetime.now().isoformat(timespec='seconds')}\n",
        encoding="utf-8",
    )

    return MigrationBackup(
        directory=target,
        revision=current_revision,
        copied_files=tuple(copied),
    )
