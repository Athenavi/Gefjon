"""数据库连接串的解析与安全呈现。

解析顺序（fail-closed）：

1. ``DATABASE_DSN`` 环境变量；
2. ``data/install.lock``（需要 ``APP_SECRET``，解密失败即报错）；
3. alembic.ini 的 ``sqlalchemy.url``。

第 2 步只要文件存在就不允许静默跳过 —— 旧实现解密失败会回退到
alembic.ini，可能把迁移打到另一个数据库上。
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

from .errors import ConfigError
from .install_lock import decrypt_dsn, read_lock_file

LOCK_RELATIVE_PATH = Path("data") / "install.lock"


def safe_url(url: str | None) -> str:
    """返回把密码遮掉的连接串，用于日志。

    遮盖基于原始字符串、覆盖 scheme 到**最后一个** ``@`` 之间的全部内容，
    因此密码里含未编码的 ``@``、``#``、``/`` 也不会泄漏；无法判断时宁可多遮。
    """
    if not url:
        return "(none)"
    separator = url.find("://")
    if separator == -1:
        return url
    prefix, rest = url[: separator + 3], url[separator + 3 :]
    at = rest.rfind("@")
    if at == -1:
        return url
    userinfo, host = rest[:at], rest[at + 1 :]
    if ":" in userinfo:
        userinfo = userinfo.split(":", 1)[0] + ":***"
    return f"{prefix}{userinfo}@{host}"


def normalize_url(url: str) -> str:
    """让 SQLAlchemy 能正确解析连接串。

    密码若未做 URL 编码且含 ``@``，authority 段会出现多个 ``@``，
    SQLAlchemy 会把密码的一部分当成主机名。只在能明确判断“密码未编码”
    （authority 段存在多个 ``@``）时才重新编码，避免把已编码的密码再次编码。
    """
    separator = url.find("://")
    if separator == -1:
        return url
    prefix, rest = url[: separator + 3], url[separator + 3 :]

    cut = len(rest)
    for character in "/?#":
        index = rest.find(character)
        if index != -1 and index < cut:
            cut = index
    authority, tail = rest[:cut], rest[cut:]

    if authority.count("@") <= 1:
        return url

    userinfo, hostport = authority.rsplit("@", 1)
    if ":" not in userinfo:
        return url

    user, password = userinfo.split(":", 1)
    return f"{prefix}{quote(user, safe='')}:{quote(password, safe='')}@{hostport}{tail}"


def resolve_database_url(
    *,
    ini_url: str | None,
    project_root: Path,
    environ: dict[str, str] | None = None,
) -> str:
    """解析并规范化数据库连接串。

    Raises:
        ConfigError: 存在 install.lock 却无法解密，或没有任何可用的连接串。
    """
    environ = os.environ if environ is None else environ

    dsn = environ.get("DATABASE_DSN")
    if dsn:
        return normalize_url(dsn.strip())

    lock_path = project_root / LOCK_RELATIVE_PATH
    if lock_path.exists():
        secret = environ.get("APP_SECRET")
        if not secret:
            raise ConfigError(
                f"检测到 {lock_path}，但没有设置 APP_SECRET，拒绝回退到其它连接串。"
                "请设置 APP_SECRET，或删除 install.lock。"
            )
        payload = read_lock_file(lock_path)
        return normalize_url(decrypt_dsn(payload, secret))

    if ini_url:
        return normalize_url(ini_url.strip())

    raise ConfigError(
        "无法确定数据库连接串：请设置 DATABASE_DSN 环境变量，"
        "或提供 data/install.lock（配合 APP_SECRET），"
        "或在 alembic.ini 中配置 sqlalchemy.url"
    )
