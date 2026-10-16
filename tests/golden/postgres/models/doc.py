"""文档 模型 —— 由 Gefjon 生成，请勿手动修改。

模型：Doc
表名：docs
"""
from sqlalchemy import Column, Index, Integer, String, Text, Uuid, event, text
from sqlalchemy.dialects.postgresql import ARRAY, BIT, DOMAIN, INET, JSONB, TIMESTAMP
from ._gefjon_types import POLYGON
from .base import Base


class Doc(Base):
    """文档"""

    __tablename__ = 'docs'
    __table_args__ = (
        Index('ix_docs_payload', 'payload', postgresql_using='gin', postgresql_ops={'payload': 'jsonb_path_ops'}),
        Index('ix_docs_addr', 'addr', postgresql_where=text('addr IS NOT NULL')),
        Index('ix_docs_lower_payload', text('lower(payload)'), postgresql_concurrently=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True, doc='id')
    payload = Column(JSONB, nullable=False, doc='payload')
    tags = Column(ARRAY(Text), nullable=False, doc='tags')
    addr = Column(INET, nullable=False, doc='addr')
    uid = Column(Uuid, nullable=False, doc='uid')
    seen_at = Column(TIMESTAMP(timezone=True), nullable=False, doc='seen_at')
    bits = Column(BIT(8, varying=True), nullable=False, doc='bits')
    shape = Column(POLYGON, nullable=False, doc='shape')
    postal_code = Column(DOMAIN('us_postal_code', String(5), not_null=True), nullable=False, doc='postal_code')

    def to_dict(self):
        """返回 {列名: 值} 的字典。"""
        return {
            attribute.key: getattr(self, attribute.key)
            for attribute in self.__mapper__.column_attrs
        }

    def __repr__(self):
        primary_key = self.__mapper__.primary_key
        values = ", ".join(
            f"{column.key}={getattr(self, column.key)!r}" for column in primary_key
        )
        return f"<Doc {values}>"

# PostgreSQL UNLOGGED 表：SQLAlchemy 没有对应参数，建表后立刻改属性
@event.listens_for(Doc.__table__, "after_create")
def _gefjon_set_unlogged_doc(target, connection, **kw):
    connection.execute(text(f"ALTER TABLE {target.name} SET UNLOGGED"))
