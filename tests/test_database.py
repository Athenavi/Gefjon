"""连接串的安全呈现、归一化与 fail-closed 解析。"""

from __future__ import annotations

from pathlib import Path

import pytest

from gefjon.database import normalize_url, resolve_database_url, safe_url
from gefjon.errors import ConfigError
from gefjon.install_lock import encrypt_dsn, write_lock_file


class TestSafeUrl:
    def test_masks_password(self) -> None:
        assert (
            safe_url("postgresql://app:S3cret@db.internal:5432/prod")
            == "postgresql://app:***@db.internal:5432/prod"
        )

    def test_masks_when_password_contains_at(self) -> None:
        masked = safe_url("postgresql://app:p@ssw0rd@localhost/prod")
        assert masked == "postgresql://app:***@localhost/prod"
        assert "ssw0rd" not in masked

    def test_masks_when_password_contains_hash(self) -> None:
        masked = safe_url("postgresql://app:p@ss#word@db.example.com/prod")
        assert "word" not in masked

    def test_without_credentials_is_unchanged(self) -> None:
        assert safe_url("sqlite:///var/lib/app.db") == "sqlite:///var/lib/app.db"

    def test_none(self) -> None:
        assert safe_url(None) == "(none)"

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql://app:S3cret@db.internal:5432/prod",
            "mysql://app:S3cret@localhost:3306/prod",
            "postgres://app:S3cret@db.internal:5432/prod",
        ],
    )
    def test_never_leaks_any_password(self, url: str) -> None:
        assert "S3cret" not in safe_url(url)


class TestNormalizeUrl:
    def test_encodes_unencoded_password(self) -> None:
        assert (
            normalize_url("postgresql://app:p@ssw0rd@localhost/prod")
            == "postgresql://app:p%40ssw0rd@localhost/prod"
        )

    def test_does_not_double_encode(self) -> None:
        url = "postgresql://app:p%40ss@db.example.com:5432/prod"
        assert normalize_url(url) == url

    def test_plain_url_is_unchanged(self) -> None:
        url = "postgresql://app:S3cret@db.internal:5432/prod"
        assert normalize_url(url) == url

    def test_sqlite_is_unchanged(self) -> None:
        assert normalize_url("sqlite:///app.db") == "sqlite:///app.db"


class TestResolve:
    def test_env_var_wins(self, tmp_path: Path) -> None:
        result = resolve_database_url(
            ini_url="sqlite:///ini.db",
            project_root=tmp_path,
            environ={"DATABASE_DSN": "sqlite:///env.db"},
        )
        assert result == "sqlite:///env.db"

    def test_ini_fallback(self, tmp_path: Path) -> None:
        result = resolve_database_url(
            ini_url="sqlite:///ini.db", project_root=tmp_path, environ={}
        )
        assert result == "sqlite:///ini.db"

    def test_nothing_available_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="无法确定数据库连接串"):
            resolve_database_url(ini_url=None, project_root=tmp_path, environ={})

    def test_lock_without_secret_fails_closed(self, tmp_path: Path) -> None:
        """install.lock 存在却缺 APP_SECRET 时必须报错，而不是回退到 ini。"""
        lock = tmp_path / "data" / "install.lock"
        write_lock_file(lock, encrypt_dsn("sqlite:///lock.db", "s3cret"))

        with pytest.raises(ConfigError, match="没有设置 APP_SECRET"):
            resolve_database_url(
                ini_url="sqlite:///ini.db", project_root=tmp_path, environ={}
            )

    def test_lock_with_wrong_secret_fails_closed(self, tmp_path: Path) -> None:
        lock = tmp_path / "data" / "install.lock"
        write_lock_file(lock, encrypt_dsn("sqlite:///lock.db", "s3cret"))

        with pytest.raises(ConfigError, match="解密失败"):
            resolve_database_url(
                ini_url="sqlite:///ini.db",
                project_root=tmp_path,
                environ={"APP_SECRET": "wrong"},
            )

    def test_lock_with_correct_secret(self, tmp_path: Path) -> None:
        lock = tmp_path / "data" / "install.lock"
        write_lock_file(lock, encrypt_dsn("postgresql://u:p@h/db", "s3cret"))

        result = resolve_database_url(
            ini_url="sqlite:///ini.db",
            project_root=tmp_path,
            environ={"APP_SECRET": "s3cret"},
        )
        assert result == "postgresql://u:p@h/db"
