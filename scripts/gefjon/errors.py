"""Gefjon 的异常层次。

所有面向用户的失败都通过 GefjonError 的子类抛出，CLI 统一转成
非零退出码，不用裸 Exception 吞掉错误。
"""


class GefjonError(Exception):
    """Gefjon 错误的基类。"""


class ConfigError(GefjonError):
    """models.yaml 不存在、结构非法，或某个取值不被接受。"""


class GenerationError(GefjonError):
    """生成模型代码时失败（渲染、校验、写文件）。"""


class MigrationError(GefjonError):
    """调用 Alembic 失败，或迁移环境未初始化。"""
