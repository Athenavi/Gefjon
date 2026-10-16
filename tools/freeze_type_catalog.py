"""把 v0.1（Python 版）的类型目录导出为 JSON 快照。

用途：Go 版的类型目录必须与 v0.1 **逐项一致**（类型名、模块、方言、参数上限、
values/item_type/timezone 支持、别名、key 与额外参数）。凭记忆移植容易漏，
因此先把权威版本冻成快照，再让 Go 侧对着它写、对着它测。

用法：
    python tools/freeze_type_catalog.py

产物：
    tests/golden/type-catalog.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from gefjon.types import _SPECS  # noqa: E402

TARGET = REPO_ROOT / "tests" / "golden" / "type-catalog.json"


def main() -> int:
    catalog = [
        {
            "name": spec.name,
            "module": spec.module,
            "dialect": spec.dialect or "",
            "min_args": spec.min_args,
            "max_args": spec.max_args,
            "takes_values": spec.takes_values,
            "takes_item_type": spec.takes_item_type,
            "takes_timezone": spec.takes_timezone,
            "takes_domain": spec.takes_domain,
            "takes_not_null": spec.takes_not_null,
            "key": spec.key or "",
            "extra_args": list(spec.extra_args),
            "aliases": list(spec.aliases),
            "udt": spec.udt,
        }
        for spec in _SPECS
    ]
    catalog.sort(key=lambda item: (item["module"], item["name"], item["key"]))

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(
        json.dumps({"types": catalog}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] {len(catalog)} 个类型 -> {TARGET.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
