"""用户 模型 —— 由 Gefjon 生成，请勿手动修改。

模型：User
表名：users
"""
from sqlalchemy import Column, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .base import Base


class User(Base):
    """用户"""

    __tablename__ = 'users'
    __table_args__ = (
        UniqueConstraint('email', 'username', name='uq_users_email_username'),
        Index('ix_users_email', 'email', unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True, doc='id')
    username = Column(String(50), nullable=False, unique=True, doc='username')
    email = Column(String(100), nullable=False, index=True, doc='email')
    created_at = Column(DateTime, nullable=False, default=func.now(), doc='created_at')
    extra_metadata = Column('metadata', Text, nullable=True, doc='metadata')

    posts = relationship('Post', back_populates='author')

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
        return f"<User {values}>"
