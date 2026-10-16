"""用当前（Python 版）实现固化 golden fixtures。

用途：Go 版重写时以这些快照作为**验收基准**（逐字节比对）。
在删除 Python 实现之前先把产物冻住，"与 v0.1 逐字节一致"才是可执行的验收条件。

用法：
    python tools/freeze_golden.py

产物：
    tests/golden/<case>/models.yaml     # 输入（固定，不含时间戳等易变内容）
    tests/golden/<case>/models/**.py    # 期望产物
    tests/golden/<case>/manifest.json   # 文件 -> SHA256
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from gefjon.config import load_config  # noqa: E402
from gefjon.generator import generate_models  # noqa: E402

GOLDEN_DIR = REPO_ROOT / "tests" / "golden"

#: 三份覆盖性输入：通用类型 / PostgreSQL 专有 / MySQL 专有
CASES: dict[str, str] = {
    "basic": textwrap.dedent(
        """\
        project:
          name: golden-basic
          version: 1.0.0

        database:
          dialect: sqlite

        models:
          - name: User
            table: users
            description: 用户
            fields:
              - name: id
                type: Integer
                primary_key: true
              - name: username
                type: String(50)
                nullable: false
                unique: true
              - name: email
                type: String(100)
                nullable: false
                index: true
              - name: created_at
                type: DateTime
                default: "func.now()"
              - name: metadata
                type: Text
                nullable: true
            indexes:
              - columns: [email]
                unique: true
            unique_constraints:
              - name: uq_users_email_username
                columns: [email, username]
            relationships:
              - name: posts
                target: Post
                back_populates: author

          - name: Post
            table: posts
            module: blog
            description: 文章
            fields:
              - name: id
                type: Integer
                primary_key: true
              - name: title
                type: String(200)
                nullable: false
              - name: content
                type: Text
                nullable: true
              - name: user_id
                type: Integer
                foreign_key: users.id
            relationships:
              - name: author
                target: User
                back_populates: posts
                cascade: "all, delete-orphan"
                lazy: selectin
        """
    ),
    "postgres": textwrap.dedent(
        """\
        project:
          name: golden-postgres
          version: 2.0.0

        database:
          dialect: postgresql

        models:
          - name: Doc
            table: docs
            description: 文档
            unlogged: true
            fields:
              - name: id
                type: Integer
                primary_key: true
              - name: payload
                type: JSONB
              - name: tags
                type: pg.ARRAY
                item_type: Text
              - name: addr
                type: INET
              - name: uid
                type: uuid
              - name: seen_at
                type: pg.TIMESTAMP
                timezone: true
              - name: bits
                type: varbit(8)
              - name: shape
                type: pg.POLYGON
              - name: postal_code
                type: DOMAIN
                domain_name: us_postal_code
                item_type: String(5)
                not_null: true
            indexes:
              - columns: [payload]
                using: gin
                ops: {payload: jsonb_path_ops}
              - columns: [addr]
                where: "addr IS NOT NULL"
              - expressions: ["lower(payload)"]
                concurrently: true
        """
    ),
    "mysql": textwrap.dedent(
        """\
        project:
          name: golden-mysql
          version: 3.0.0

        database:
          dialect: mysql

        models:
          - name: Product
            table: products
            description: 商品
            fields:
              - name: id
                type: Integer
                primary_key: true
              - name: sku
                type: VARCHAR(64)
                nullable: false
                unique: true
              - name: body
                type: LONGTEXT
              - name: flags
                type: mysql.SET
                values: [a, b, c]
              - name: released_year
                type: YEAR
              - name: price
                type: mysql.DECIMAL(10, 2)
            indexes:
              - columns: [body]
                prefix: fulltext
              - columns: [sku]
                lengths: {sku: 32}
        """
    ),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_case(name: str, config_text: str) -> dict:
    workdir = Path(tempfile.mkdtemp())
    (workdir / "models.yaml").write_text(config_text, encoding="utf-8")

    config = load_config(workdir / "models.yaml")
    generate_models(config, workdir / "models", project_root=workdir, backup=False)

    target = GOLDEN_DIR / name
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    (target / "models.yaml").write_text(config_text, encoding="utf-8")

    files: dict[str, str] = {}
    for path in sorted((workdir / "models").rglob("*.py")):
        relative = path.relative_to(workdir / "models").as_posix()
        destination = target / "models" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        files[f"models/{relative}"] = _sha256(destination)

    manifest = {"case": name, "files": files}
    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in CASES.items():
        manifest = freeze_case(name, text)
        print(f"[OK] {name}: {len(manifest['files'])} 个文件")
    print(f"golden fixtures 已写入 {GOLDEN_DIR.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
