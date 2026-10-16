"""SQLAlchemy 未内置的方言类型 —— 由 Gefjon 生成，请勿手动修改。

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


class POLYGON(_GefjonNamedType):
    sql_name = "POLYGON"
