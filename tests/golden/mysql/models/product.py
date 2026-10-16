"""商品 模型 —— 由 Gefjon 生成，请勿手动修改。

模型：Product
表名：products
"""
from sqlalchemy import Column, Index, Integer, String
from sqlalchemy.dialects.mysql import DECIMAL, LONGTEXT, SET, YEAR
from .base import Base


class Product(Base):
    """商品"""

    __tablename__ = 'products'
    __table_args__ = (
        Index('ix_products_body', 'body', mysql_prefix='FULLTEXT'),
        Index('ix_products_sku', 'sku', mysql_length={'sku': 32}),
    )

    id = Column(Integer, primary_key=True, autoincrement=True, doc='id')
    sku = Column(String(64), nullable=False, unique=True, doc='sku')
    body = Column(LONGTEXT, nullable=False, doc='body')
    flags = Column(SET('a', 'b', 'c'), nullable=False, doc='flags')
    released_year = Column(YEAR, nullable=False, doc='released_year')
    price = Column(DECIMAL(10, 2), nullable=False, doc='price')

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
        return f"<Product {values}>"
