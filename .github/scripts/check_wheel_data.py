"""断言构建出的 wheel 里包含运行期必需的包数据。

背景：pyproject 的 ``package-data`` 一旦漏配（例如写成 ``*.ini`` 而实际文件名是
``*.template``），在源码目录里跑测试是发现不了的 —— 只有安装之后才会报
「内置脚手架缺少文件」。把这条检查放进 CI，避免同类问题再次发布出去。

用法：
    python -m build --wheel
    python .github/scripts/check_wheel_data.py
"""

from __future__ import annotations

import glob
import sys
import zipfile
from pathlib import Path

#: 运行期必需的文件（相对于 wheel 根）
REQUIRED = (
    "gefjon/templates/orm_model.py.jinja2",
    "gefjon/alembic_scaffold/env.py",
    "gefjon/alembic_scaffold/script.py.mako",
    "gefjon/alembic_scaffold/alembic.ini.template",
)


def main() -> int:
    wheels = sorted(glob.glob("dist/*.whl"))
    if not wheels:
        print("[FAIL] 找不到 dist/*.whl，请先运行 `python -m build --wheel`")
        return 1

    wheel = wheels[-1]
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())

    print(f"wheel: {Path(wheel).name}")
    package_data = sorted(n for n in names if "scaffold" in n or "templates/" in n)
    print(f"包数据: {package_data}")

    missing = [name for name in REQUIRED if name not in names]
    if missing:
        print("[FAIL] wheel 缺少运行期必需的文件：")
        for name in missing:
            print(f"   - {name}")
        return 1

    entry_points = "gefjon-0.1.0.dist-info/entry_points.txt"
    if not any(name.endswith("entry_points.txt") for name in names):
        print("[FAIL] wheel 缺少 entry_points.txt（gefjon 命令不会生成）")
        return 1

    print("[OK] 包数据与入口点齐全")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
