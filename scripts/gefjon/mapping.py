"""第三方项目版本 <-> 数据库版本的映射缓存。

持久化到 ``<project_root>/.gefjon/version_map.json``，供 ``gefjon status``
展示。写入同样是原子的：临时文件 + ``os.replace``。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ThirdPartyMapping
from .errors import GefjonError

STATE_DIRNAME = ".gefjon"
VERSION_MAP_FILENAME = "version_map.json"


@dataclass
class VersionMap:
    """当前项目版本与数据库 revision 的对应关系。"""

    project_name: str = ""
    project_version: str = ""
    db_revision: str | None = None
    updated_at: str = ""
    third_party: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def from_third_party(
        cls,
        project_name: str,
        project_version: str,
        mappings: tuple[ThirdPartyMapping, ...] = (),
    ) -> "VersionMap":
        return cls(
            project_name=project_name,
            project_version=project_version,
            third_party=[asdict(mapping) for mapping in mappings],
        )


def state_dir(project_root: Path) -> Path:
    return project_root / STATE_DIRNAME


def version_map_path(project_root: Path) -> Path:
    return state_dir(project_root) / VERSION_MAP_FILENAME


def load_version_map(project_root: Path) -> VersionMap | None:
    """读取映射缓存；不存在或损坏时返回 None（不抛异常）。"""
    path = version_map_path(project_root)
    if not path.exists():
        return None
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict):
        return None

    third_party = raw.get("third_party")
    if not isinstance(third_party, list):
        third_party = []

    return VersionMap(
        project_name=str(raw.get("project_name") or ""),
        project_version=str(raw.get("project_version") or ""),
        db_revision=str(raw["db_revision"]) if raw.get("db_revision") else None,
        updated_at=str(raw.get("updated_at") or ""),
        third_party=[entry for entry in third_party if isinstance(entry, dict)],
    )


def save_version_map(project_root: Path, version_map: VersionMap) -> Path:
    """原子写入映射缓存。"""
    path = version_map_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    version_map.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    payload = json.dumps(asdict(version_map), indent=2, ensure_ascii=False) + "\n"
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        raise GefjonError(f"写入版本映射失败：{exc}") from exc
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)

    return path
