"""验证 golden fixtures 的完整性与可复现性。

golden fixtures（``tests/golden/``）是 Go 版重写的**验收基准**。这里保证两件事：

1. fixtures 没有被手改 —— manifest 里的 SHA256 与文件内容一致；
2. 它们确实是**当前实现的可复现产物** —— 用当前实现重新生成，结果逐字节相同。

没有第 2 条，"与 v0.1 逐字节一致"这句话就是不可验证的。
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import pytest

from gefjon.config import load_config
from gefjon.generator import generate_models

GOLDEN_DIR = Path(__file__).parent / "golden"
CASES = (
    sorted(path.name for path in GOLDEN_DIR.iterdir() if path.is_dir())
    if GOLDEN_DIR.exists()
    else []
)


def test_golden_cases_exist() -> None:
    assert CASES, f"未找到 golden fixtures：{GOLDEN_DIR}（先运行 python tools/freeze_golden.py）"
    for case in CASES:
        assert (GOLDEN_DIR / case / "models.yaml").is_file(), f"{case} 缺少输入 models.yaml"
        assert (GOLDEN_DIR / case / "manifest.json").is_file(), f"{case} 缺少 manifest.json"


@pytest.mark.parametrize("case", CASES)
def test_golden_manifest_matches_files(case: str) -> None:
    root = GOLDEN_DIR / case
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["case"] == case
    for relative, digest in sorted(manifest["files"].items()):
        path = root / relative
        assert path.is_file(), f"{case} 缺少 {relative}"
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == digest, f"{case} 的 {relative} 与 manifest 不一致（fixtures 被手改过？）"


@pytest.mark.parametrize("case", CASES)
def test_current_implementation_reproduces_golden(case: str) -> None:
    """用当前实现重新生成，产物必须与 fixtures 逐字节一致。"""
    root = GOLDEN_DIR / case
    workdir = Path(tempfile.mkdtemp())
    (workdir / "models.yaml").write_text(
        (root / "models.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )

    config = load_config(workdir / "models.yaml")
    generate_models(config, workdir / "models", project_root=workdir, backup=False)

    def snapshot(base: Path) -> dict[str, str]:
        return {
            path.relative_to(base).as_posix(): path.read_text(encoding="utf-8")
            for path in sorted(base.rglob("*.py"))
        }

    assert snapshot(workdir / "models") == snapshot(root / "models")
