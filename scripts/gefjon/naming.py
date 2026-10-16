"""命名转换与标识符校验。

生成器会把 YAML 中的名字直接写进生成的 Python 源码，因此这里
既做转换，也做**白名单校验** —— 只有合法的 Python 标识符才允许进入模板，
从根上排除代码注入。
"""

from __future__ import annotations

import keyword
import re

_FIRST_BOUNDARY = re.compile(r"(.)([A-Z][a-z]+)")
_SECOND_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: 生成器不会用到的名字，避免覆盖 SQLAlchemy 声明式基类的属性
RESERVED_NAMES = frozenset(
    {
        "metadata",
        "registry",
        "query",
        "session",
    }
)

_PYTHON_KEYWORDS = frozenset(keyword.kwlist) | {"True", "False", "None"}


def is_valid_identifier(name: str) -> bool:
    """name 是否能安全地作为 Python 标识符写进生成代码。"""
    return bool(_IDENTIFIER.match(name)) and name not in _PYTHON_KEYWORDS


def to_snake_case(name: str) -> str:
    """``MediaAsset`` -> ``media_asset``。"""
    first = _FIRST_BOUNDARY.sub(r"\1_\2", name)
    return _SECOND_BOUNDARY.sub(r"\1_\2", first).lower()


def to_module_name(model_name: str) -> str:
    """模型名 -> 模块文件名（不含扩展名）。"""
    return to_snake_case(model_name)


def to_table_name(model_name: str, explicit: str | None = None) -> str:
    """模型名 -> 表名。

    显式配置优先；否则用 snake_case 加简单复数（``User`` -> ``users``），
    与 README 中的示例保持一致。
    """
    if explicit:
        return explicit
    base = to_snake_case(model_name)
    if not base.endswith("s"):
        base += "s"
    return base
