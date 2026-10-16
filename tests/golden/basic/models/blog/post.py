"""文章 模型 —— 由 Gefjon 生成，请勿手动修改。

模型：Post
表名：posts
"""
from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from ..base import Base


class Post(Base):
    """文章"""

    __tablename__ = 'posts'

    id = Column(Integer, primary_key=True, autoincrement=True, doc='id')
    title = Column(String(200), nullable=False, doc='title')
    content = Column(Text, nullable=True, doc='content')
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, doc='user_id')

    author = relationship('User', back_populates='posts', cascade='all, delete-orphan', lazy='selectin')

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
        return f"<Post {values}>"
