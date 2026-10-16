"""共用 fixtures。"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

SAMPLE_CONFIG = textwrap.dedent(
    """
    project:
      name: demo
      version: 1.2.3

    database:
      url: "sqlite:///./app.db"
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
    """
)


@pytest.fixture
def sample_config_text() -> str:
    return SAMPLE_CONFIG


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """带 models.yaml 的临时项目目录。"""
    (tmp_path / "models.yaml").write_text(SAMPLE_CONFIG, encoding="utf-8")
    return tmp_path
