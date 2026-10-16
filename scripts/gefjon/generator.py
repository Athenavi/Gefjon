"""把校验过的配置渲染成 SQLAlchemy 模型文件。

三条硬性保证：

1. **不写半成品**：所有文件先在内存里渲染完成，全部成功后才落盘；
   模板缺失或渲染失败只会报错，绝不会把已有模型文件清空。
2. **原子写**：写临时文件再 ``os.replace``，中途失败不会留下截断的文件。
3. **无模板注入**：写进模板的字符串全部来自 config 层的校验结果或
   ``repr()`` 转义，模板不做任何拼接。
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound

from .config import Field, GefjonConfig, Index, Model
from .errors import GenerationError
from .types import GENERATED_TYPES_MODULE, SQLALCHEMY

TEMPLATES_DIR = Path(__file__).parent / "templates"
MODEL_TEMPLATE = "orm_model.py.jinja2"

BASE_MODULE_SOURCE = '''"""所有模型的声明式基类 —— 由 Gefjon 生成，请勿手动修改。"""

from sqlalchemy.orm import declarative_base

Base = declarative_base()
'''


@dataclass(frozen=True)
class GeneratedFile:
    path: Path
    model: str


@dataclass(frozen=True)
class GenerationResult:
    output_dir: Path
    files: tuple[GeneratedFile, ...]
    backup_dir: Path | None


# ── 源码片段渲染 ─────────────────────────────────────────────────────


def _render_column(field: Field) -> str:
    """渲染一个 ``Column(...)`` 调用。

    nullable 语义在这里是**显式**的：非主键列总是写出 ``nullable=``，
    因此 ``nullable: false`` 会真正生成 NOT NULL，不再依赖 SQLAlchemy 的隐式默认。
    """
    parts: list[str] = []
    if field.column_explicit:
        parts.append(field.column_repr)
    parts.append(field.type.expression)
    if field.foreign_key:
        parts.append(f"ForeignKey({field.foreign_key_repr})")

    if field.primary_key:
        parts.append("primary_key=True")
        if field.autoincrement:
            parts.append("autoincrement=True")
    else:
        parts.append(f"nullable={field.nullable!r}")

    if field.unique:
        parts.append("unique=True")
    if field.index and not field.unique and not field.primary_key:
        parts.append("index=True")
    if field.default_sql is not None:
        parts.append(f"default={field.default_sql}")
    parts.append(f"doc={field.doc_repr}")

    return f"{field.name} = Column({', '.join(parts)})"


def _render_table_args(model: Model) -> list[str]:
    items: list[str] = []
    for constraint in model.unique_constraints:
        columns = ", ".join(constraint.column_reprs)
        if constraint.name:
            items.append(f"UniqueConstraint({columns}, name={constraint.name_repr})")
        else:
            items.append(f"UniqueConstraint({columns})")
    for index in model.indexes:
        items.append(_render_index(index))
    return items


def _render_index(index: Index) -> str:
    """渲染一个 ``Index(...)``，含表达式与方言专用参数。

    所有值都来自已被校验的配置（索引方法白名单、操作符类标识符、
    受限解析后的 where 片段与表达式），并统一用 repr 转义。
    """
    parts: list[str] = [index.name_repr, *index.column_reprs]
    for expression in index.expressions:
        parts.append(f"text({expression!r})")
    if index.unique:
        parts.append("unique=True")
    if index.using:
        parts.append(f"postgresql_using={index.using!r}")
    if index.ops:
        ops = ", ".join(f"{column!r}: {opclass!r}" for column, opclass in index.ops)
        parts.append(f"postgresql_ops={{{ops}}}")
    if index.where_sql:
        parts.append(f"postgresql_where=text({index.where_sql!r})")
    if index.concurrently:
        parts.append("postgresql_concurrently=True")
    if index.prefix:
        parts.append(f"mysql_prefix={index.prefix.upper()!r}")
    if index.lengths:
        lengths = ", ".join(
            f"{column!r}: {length}" for column, length in index.lengths
        )
        parts.append(f"mysql_length={{{lengths}}}")
    return f"Index({', '.join(parts)})"


def _render_import_lines(model: Model) -> list[str]:
    # 类型可能来自 sqlalchemy、某个方言模块，或 Gefjon 生成的辅助模块
    by_module: dict[str, set[str]] = {SQLALCHEMY: {"Column"}}
    generated: set[str] = set()
    for field in model.fields:
        for module, name in field.type.import_pairs:
            if module == GENERATED_TYPES_MODULE:
                generated.add(name)
            else:
                by_module.setdefault(module, set()).add(name)

    if any(field.foreign_key for field in model.fields):
        by_module[SQLALCHEMY].add("ForeignKey")
    if model.indexes:
        by_module[SQLALCHEMY].add("Index")
        if any(index.where_sql or index.expressions for index in model.indexes):
            by_module[SQLALCHEMY].add("text")
    if model.unique_constraints:
        by_module[SQLALCHEMY].add("UniqueConstraint")
    if model.unlogged:
        by_module[SQLALCHEMY].update({"event", "text"})

    lines = [
        f"from {module} import {', '.join(sorted(names))}"
        for module, names in sorted(by_module.items())
    ]
    lines.extend(
        sorted({field.default_import for field in model.fields if field.default_import})
    )
    depth = len(model.module.split("/")) if model.module else 0
    prefix = "." * (depth + 1)
    if generated:
        lines.append(
            f"from {prefix}{GENERATED_TYPES_MODULE} import {', '.join(sorted(generated))}"
        )
    lines.append(f"from {prefix}base import Base")
    return lines


def _render_generated_types(names: Sequence[str]) -> str:
    """生成 SQLAlchemy 未内置类型所需的 UserDefinedType 子类。"""
    header = '''"""SQLAlchemy 未内置的方言类型 —— 由 Gefjon 生成，请勿手动修改。

这些类型只负责把类型名渲染成 SQL（``get_col_spec``），具体语义由数据库决定。
"""

from sqlalchemy.types import UserDefinedType


class _GefjonNamedType(UserDefinedType):
    """按名字渲染 SQL 类型的基类。"""

    sql_name = ""

    def get_col_spec(self, **kw):
        return self.sql_name

    def __repr__(self):
        return f"{type(self).__name__}()"
'''
    blocks = [
        f'\n\nclass {name}(_GefjonNamedType):\n    sql_name = "{name}"\n'
        for name in names
    ]
    return header + "".join(blocks)


def _build_environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        # 模板引用了未提供的变量时直接报错，而不是静默渲染成空串
        undefined=StrictUndefined,
    )


# ── 包文件渲染 ───────────────────────────────────────────────────────


def _render_package_init(models: Sequence[Model]) -> str:
    lines = [
        '"""模型包 —— 由 Gefjon 生成，请勿手动修改。"""',
        "",
        "from .base import Base",
    ]
    for model in sorted(models, key=lambda item: (item.module, item.name)):
        module_ref = "." + model.module.replace("/", ".") + "." if model.module else "."
        lines.append(f"from {module_ref}{model.module_name} import {model.name}")
    lines.append("")

    exported = sorted({model.name for model in models} | {"Base"})
    names = ", ".join(f'"{name}"' for name in exported)
    lines.append(f"__all__ = [{names}]")
    return "\n".join(lines) + "\n"


def _render_subpackage_init(module: str, models: Sequence[Model]) -> str:
    depth = len(module.split("/"))
    prefix = "." * (depth + 1)
    lines = [f'"""{module} 子包 —— 由 Gefjon 生成，请勿手动修改。"""', ""]
    for model in sorted(models, key=lambda item: item.name):
        lines.append(f"from {prefix}{model.module_name} import {model.name}")
    lines.append("")
    exported = ", ".join(f'"{model.name}"' for model in sorted(models, key=lambda i: i.name))
    lines.append(f"__all__ = [{exported}]")
    return "\n".join(lines) + "\n"


# ── 落盘 ─────────────────────────────────────────────────────────────


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _backup_output_dir(output_dir: Path, project_root: Path) -> Path | None:
    if not output_dir.exists() or not any(output_dir.iterdir()):
        return None
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    target = project_root / ".gefjon" / "backups" / f"models-{stamp}"
    counter = 1
    while target.exists():
        counter += 1
        target = project_root / ".gefjon" / "backups" / f"models-{stamp}-{counter}"
    shutil.copytree(output_dir, target)
    return target


# ── 入口 ─────────────────────────────────────────────────────────────


def generate_models(
    config: GefjonConfig,
    output_dir: Path,
    *,
    project_root: Path,
    selected: Iterable[str] | None = None,
    backup: bool = True,
) -> GenerationResult:
    """渲染并写出模型包。

    Args:
        config: 已校验的配置。
        output_dir: 生成的模型包目录（例如 ``./models``）。
        project_root: 项目根目录，备份写到 ``<project_root>/.gefjon/backups``。
        selected: 只生成这些模型；None 表示全部。
        backup: 是否在覆盖前备份现有输出目录。

    Raises:
        GenerationError: 模板缺失、渲染失败或未匹配到任何模型。
    """
    models = _select_models(config, selected)

    environment = _build_environment()
    try:
        template = environment.get_template(MODEL_TEMPLATE)
    except TemplateNotFound as exc:
        raise GenerationError(
            f"模板缺失：{TEMPLATES_DIR / MODEL_TEMPLATE}（预期文件 {MODEL_TEMPLATE}）"
        ) from exc

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1) 全部渲染到内存，任何失败都在写盘之前抛出
    pending: dict[Path, str] = {}
    files: list[GeneratedFile] = []
    for model in models:
        try:
            source = template.render(
                model=model,
                import_lines=_render_import_lines(model),
                field_lines=[_render_column(field) for field in model.fields],
                table_args=_render_table_args(model),
                generation_time=generated_at,
            )
        except Exception as exc:  # 渲染失败绝不落盘
            raise GenerationError(f"渲染模型 {model.name} 失败：{exc}") from exc

        target = _model_path(output_dir, model)
        pending[target] = source
        files.append(GeneratedFile(path=target, model=model.name))

    pending[output_dir / "base.py"] = BASE_MODULE_SOURCE
    pending[output_dir / "__init__.py"] = _render_package_init(models)
    generated_types = sorted(
        {
            name
            for model in models
            for field in model.fields
            for name in field.type.generated_names
        }
    )
    if generated_types:
        pending[output_dir / f"{GENERATED_TYPES_MODULE}.py"] = _render_generated_types(
            generated_types
        )
    for module in sorted({model.module for model in models if model.module}):
        module_models = [model for model in models if model.module == module]
        pending[output_dir / module / "__init__.py"] = _render_subpackage_init(
            module, module_models
        )

    # 2) 全部渲染成功，才备份并落盘
    backup_dir = _backup_output_dir(output_dir, project_root) if backup else None
    for path, content in pending.items():
        _write_atomic(path, content)

    return GenerationResult(
        output_dir=output_dir,
        files=tuple(files),
        backup_dir=backup_dir,
    )


def _select_models(
    config: GefjonConfig, selected: Iterable[str] | None
) -> tuple[Model, ...]:
    if not config.models:
        raise GenerationError("models.yaml 中没有定义任何模型")

    if selected is None:
        return config.models

    wanted = list(selected)
    by_name = {model.name: model for model in config.models}
    missing = [name for name in wanted if name not in by_name]
    if missing:
        raise GenerationError(
            f"models.yaml 中不存在这些模型：{', '.join(missing)}；"
            f"可用模型：{', '.join(sorted(by_name))}"
        )
    return tuple(by_name[name] for name in wanted)


def _model_path(output_dir: Path, model: Model) -> Path:
    if model.module:
        return output_dir / model.module / f"{model.module_name}.py"
    return output_dir / f"{model.module_name}.py"
