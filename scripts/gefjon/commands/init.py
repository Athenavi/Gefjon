"""``gefjon init`` —— 在项目里初始化迁移目录与示例配置。"""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Optional

import typer

from ..config import DEFAULT_MIGRATIONS_DIR, DEFAULT_OUTPUT_DIR, load_config
from ..errors import GefjonError
from ..project import CONFIG_FILENAMES

SCAFFOLD_FILES = ("env.py", "script.py.mako", "alembic.ini.template")

SAMPLE_CONFIG = '''# models.yaml —— Gefjon 示例配置
project:
  name: myproject
  version: 1.0.0

database:
  url: "sqlite:///./app.db"   # 也可用 DATABASE_DSN 环境变量覆盖
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
      - name: created_at
        type: DateTime
        default: "func.now()"
    indexes:
      - columns: [email]
        unique: true

  - name: Post
    table: posts
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
        nullable: true
      - name: published_at
        type: DateTime
        nullable: true
'''


def _read_scaffold(name: str) -> str:
    try:
        package = resources.files("gefjon.alembic_scaffold")
    except (ModuleNotFoundError, TypeError) as exc:
        raise GefjonError(f"内置脚手架不可用：{exc}") from exc

    resource = package / name
    if not resource.is_file():
        raise GefjonError(f"内置脚手架缺少文件：{name}")
    return resource.read_text(encoding="utf-8")


def _render_alembic_ini(models_package: str, database_url: str | None) -> str:
    template = _read_scaffold("alembic.ini.template")
    # configparser 会把 % 当作插值语法，写入前必须转义
    escaped_url = (database_url or "").replace("%", "%%")
    return template.replace("__MODELS_PACKAGE__", models_package).replace(
        "__DATABASE_URL__", escaped_url
    )


def _emit(path: Path, content: str, *, force: bool, created: list, skipped: list) -> None:
    if path.exists() and not force:
        skipped.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    created.append(path)


def init(
    directory: Optional[Path] = typer.Option(
        None, "--directory", "-d", help=f"迁移目录（默认 {DEFAULT_MIGRATIONS_DIR}）"
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help=f"模型包目录（默认 {DEFAULT_OUTPUT_DIR}）"
    ),
    database_url: Optional[str] = typer.Option(
        None, "--database-url", help="写入 alembic.ini 的连接串（默认取 models.yaml 的 database.url）"
    ),
    force: bool = typer.Option(False, "--force", help="覆盖已存在的文件"),
) -> None:
    """初始化 Gefjon 项目结构（迁移目录、alembic.ini、env.py、示例 models.yaml）。"""
    root = Path.cwd()
    migration_dir = root / (directory or Path(DEFAULT_MIGRATIONS_DIR))
    output_dir = output or Path(DEFAULT_OUTPUT_DIR)

    created: list[Path] = []
    skipped: list[Path] = []

    # 1) 先确定 models.yaml，这样 alembic.ini 能直接写上连接串
    config_path = next(
        (root / name for name in CONFIG_FILENAMES if (root / name).exists()), None
    )
    if config_path is None:
        config_path = root / CONFIG_FILENAMES[0]
        _emit(config_path, SAMPLE_CONFIG, force=force, created=created, skipped=skipped)

    effective_url = database_url
    if not effective_url:
        try:
            effective_url = load_config(config_path).database.url
        except GefjonError:
            effective_url = None

    try:
        models_package = output_dir.as_posix().strip("/").replace("/", ".")
        ini_source = _render_alembic_ini(models_package, effective_url)
        env_source = _read_scaffold("env.py")
        mako_source = _read_scaffold("script.py.mako")
    except GefjonError as exc:
        typer.secho(f"错误：{exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    _emit(migration_dir / "alembic.ini", ini_source, force=force, created=created, skipped=skipped)
    _emit(migration_dir / "env.py", env_source, force=force, created=created, skipped=skipped)
    _emit(
        migration_dir / "script.py.mako",
        mako_source,
        force=force,
        created=created,
        skipped=skipped,
    )

    versions_dir = migration_dir / "versions"
    versions_dir.mkdir(parents=True, exist_ok=True)
    keep = versions_dir / ".gitkeep"
    if not keep.exists():
        keep.write_text("", encoding="utf-8")
        created.append(keep)

    for path in created:
        typer.secho(f"  + 已创建 {path.relative_to(root)}", fg=typer.colors.GREEN)
    for path in skipped:
        typer.secho(f"  - 已存在，跳过 {path.relative_to(root)}", fg=typer.colors.YELLOW)

    if not created and skipped:
        typer.echo("没有新增文件；如需覆盖请加 --force")
    typer.secho("初始化完成", fg=typer.colors.GREEN)
