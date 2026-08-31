"""Secrets vault tests — mode enforcement, symlink traps, migration, legacy
fallback + deprecation, credentials-dir bridge. All on tmp trees; never
touches the real ~/.agent-reach."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kortex_search.extract import vault


@pytest.fixture
def vault_env(tmp_path, monkeypatch):
    """Point the vault at a tmp tree and reset module state."""
    monkeypatch.setattr(vault, "VAULT_DIR", str(tmp_path))
    monkeypatch.setattr(vault, "PERSONA", "kaiser")
    monkeypatch.setattr("kortex_search.config.CREDENTIALS_DIR", "")
    vault._CONFIG_PATHS["twitter"] = str(tmp_path / "kaiser" / "twitter.env")
    vault._CONFIG_PATHS["deepseek"] = str(tmp_path / "kaiser" / "deepseek.env")
    vault._CONFIG_PATHS["proxy"] = str(tmp_path / "kaiser" / "proxy.env")
    vault.LEGACY_PATHS["twitter"] = str(tmp_path / "legacy" / "twitter-auth.env")
    vault.LEGACY_PATHS["deepseek"] = str(tmp_path / "legacy" / "deepseek.env")
    vault.LEGACY_PATHS["proxy"] = str(tmp_path / "legacy" / "proxy.env")
    (tmp_path / "legacy").mkdir()
    return tmp_path


def _write(path: Path, body: str, mode: int = 0o600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    os.chmod(path, mode)
    return path


class TestMigration:
    def test_dry_run_moves_nothing(self, vault_env):
        legacy = _write(vault_env / "legacy" / "twitter-auth.env",
                        "TWITTER_AUTH_TOKEN=abc\nTWITTER_CT0=def\n")
        rows = vault.migrate(dry_run=True)
        assert rows[0]["status"] == "migrated"
        assert legacy.exists()  # untouched
        assert not (vault_env / "kaiser" / "twitter.env").exists()

    def test_real_migration_moves_and_filters(self, vault_env):
        _write(vault_env / "legacy" / "twitter-auth.env",
               "# comment\nTWITTER_AUTH_TOKEN=abc\nTWITTER_CT0=def\nOTHER=zzz\n")
        _write(vault_env / "legacy" / "deepseek.env", "DEEPSEEK_API_KEY=sk-x\n")
        rows = {r["kind"]: r for r in vault.migrate()}
        assert rows["twitter"]["status"] == "migrated"
        assert rows["deepseek"]["status"] == "migrated"
        assert rows["proxy"]["status"] == "noop"  # never existed
        assert not (vault_env / "legacy" / "twitter-auth.env").exists()
        content = (vault_env / "kaiser" / "twitter.env").read_text()
        assert "TWITTER_AUTH_TOKEN=abc" in content
        assert "TWITTER_CT0=def" in content
        assert "OTHER" not in content  # only declared keys move
        assert (vault_env / "kaiser" / "twitter.env").stat().st_mode & 0o777 == 0o600
        assert (vault_env / "kaiser").stat().st_mode & 0o777 == 0o700

    def test_partial_failure_reports(self, vault_env, monkeypatch):
        _write(vault_env / "legacy" / "deepseek.env", "DEEPSEEK_API_KEY=sk-x\n")

        def boom(*_a, **_k):
            raise OSError("nope")

        monkeypatch.setattr(vault, "_atomic_write_0600", boom)
        rows = {r["kind"]: r for r in vault.migrate()}
        assert rows["deepseek"]["status"].startswith("error:")


class TestEnvFileResolution:
    def test_vault_path_wins(self, vault_env):
        _write(vault_env / "kaiser" / "twitter.env", "TWITTER_AUTH_TOKEN=abc\n")
        assert vault.env_file_for("twitter") == str(
            vault_env / "kaiser" / "twitter.env")

    def test_legacy_paths_no_longer_honored(self, vault_env):
        # D7.3: the legacy flat paths are migration-source only since 0.4.3 —
        # env_file_for returns the configured vault path even when a legacy
        # file still exists (a never-migrated machine must migrate first)
        _write(vault_env / "legacy" / "twitter-auth.env",
               "TWITTER_AUTH_TOKEN=abc\n")
        assert vault.env_file_for("twitter") == str(
            vault_env / "kaiser" / "twitter.env")
        assert vault.load_secrets("twitter", {"TWITTER_AUTH_TOKEN"}) == {}

    def test_load_secrets_through_chain(self, vault_env):
        _write(vault_env / "kaiser" / "deepseek.env", "DEEPSEEK_API_KEY=sk-vault\n")
        assert vault.load_secrets("deepseek", {"DEEPSEEK_API_KEY"}) == {
            "DEEPSEEK_API_KEY": "sk-vault"}
        # missing file → explicit empty (callers degrade, never crash)
        assert vault.load_secrets("proxy", {"K"}) == {}

    def test_credentials_dir_bridge_wins(self, vault_env, monkeypatch):
        _write(vault_env / "cred" / "deepseek.env", "DEEPSEEK_API_KEY=sk-cred\n")
        _write(vault_env / "kaiser" / "deepseek.env", "DEEPSEEK_API_KEY=sk-vault\n")
        monkeypatch.setattr("kortex_search.config.CREDENTIALS_DIR",
                            str(vault_env / "cred"))
        assert vault.load_secrets("deepseek", {"DEEPSEEK_API_KEY"}) == {
            "DEEPSEEK_API_KEY": "sk-cred"}
        # bridge off → vault file
        monkeypatch.setattr("kortex_search.config.CREDENTIALS_DIR", "")
        assert vault.load_secrets("deepseek", {"DEEPSEEK_API_KEY"}) == {
            "DEEPSEEK_API_KEY": "sk-vault"}


@pytest.fixture
def outside(tmp_path_factory):
    return tmp_path_factory.mktemp("vault-outside")


class TestHygiene:
    def test_mode_enforcement(self, vault_env):
        _write(vault_env / "kaiser" / "twitter.env", "TWITTER_AUTH_TOKEN=a\n", 0o644)
        findings = vault.hygiene()
        modes = [f for f in findings if f.kind == "mode"]
        assert modes and modes[0].severity == "error"

    def test_symlink_trap_escape(self, vault_env, outside):
        real = _write(outside / "secret.env", "K=V\n")
        (vault_env / "kaiser").mkdir(parents=True, exist_ok=True)
        (vault_env / "kaiser" / "twitter.env").symlink_to(real)
        findings = vault.hygiene()
        traps = [f for f in findings if f.kind == "symlink"]
        assert traps and traps[0].severity == "error"
        assert "escapes" in traps[0].message

    def test_stale_file(self, vault_env):
        p = _write(vault_env / "kaiser" / "twitter.env", "TWITTER_AUTH_TOKEN=a\n")
        os.utime(p, (1, 1))  # 1970 — way past 90 days
        findings = vault.hygiene()
        assert any(f.kind == "stale" for f in findings)

    def test_out_of_vault_config(self, vault_env, monkeypatch, outside):
        external = _write(outside / "deepseek.env", "K=V\n")
        monkeypatch.setitem(vault._CONFIG_PATHS, "deepseek", str(external))
        findings = vault.hygiene()
        assert any(f.kind == "out-of-vault" for f in findings)

    def test_clean_vault_no_findings(self, vault_env):
        _write(vault_env / "kaiser" / "twitter.env", "TWITTER_AUTH_TOKEN=a\n")
        findings = vault.hygiene()
        assert not [f for f in findings if f.severity in ("warn", "error")]

    def test_missing_vault_is_warn(self, vault_env, monkeypatch):
        monkeypatch.setattr(vault, "VAULT_DIR", str(vault_env / "nope"))
        findings = vault.hygiene()
        assert findings and findings[0].severity == "warn"


class TestStatus:
    def test_status_shape_and_hygiene_ok(self, vault_env):
        _write(vault_env / "kaiser" / "twitter.env", "TWITTER_AUTH_TOKEN=a\n")
        st = vault.status()
        assert st["persona"] == "kaiser"
        assert st["hygiene"]["ok"] is True
        kaiser = [p for p in st["profiles"] if p["persona"] == "kaiser"]
        assert kaiser == [{"persona": "kaiser", "files": ["twitter.env"]}]

    def test_findings_red(self, vault_env):
        _write(vault_env / "kaiser" / "twitter.env", "TWITTER_AUTH_TOKEN=a\n", 0o644)
        st = vault.status()
        assert st["hygiene"]["ok"] is False
        assert any(f["kind"] == "mode" for f in st["hygiene"]["findings"])


# --------------------------------------------------------------------------
# TOCTOU hardening (sweep 2026-08-31): symlink-refusing mkdir + atomic 0600
# writes (O_EXCL + O_NOFOLLOW)
# --------------------------------------------------------------------------

class TestMigrationHardening:
    def test_safe_mkdir_refuses_symlink_component(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        (tmp_path / "link").symlink_to(real)
        with pytest.raises(OSError, match="symlink"):
            vault._safe_mkdir(tmp_path / "link" / "vault")

    def test_safe_mkdir_accepts_clean_path(self, tmp_path):
        p = tmp_path / "a" / "b"
        vault._safe_mkdir(p)
        assert p.is_dir()

    def test_atomic_write_0600_no_follow(self, tmp_path):
        f = tmp_path / "secret.env"
        vault._atomic_write_0600(f, "K=v\n")
        assert f.read_text() == "K=v\n"
        assert (f.stat().st_mode & 0o777) == 0o600

    def test_atomic_write_refuses_symlink_target(self, tmp_path):
        real = tmp_path / "real.txt"
        real.write_text("original")
        link = tmp_path / "link.tmp"
        link.symlink_to(real)
        # O_EXCL sees the symlink as existing and the handler unlinks the
        # SYMLINK (never its target), then writes a fresh regular file —
        # the target must stay untouched and the path must end up regular
        vault._atomic_write_0600(link, "K=v\n")
        assert real.read_text() == "original"
        assert not link.is_symlink()
        assert link.read_text() == "K=v\n"
        assert (link.stat().st_mode & 0o777) == 0o600

    def test_migrate_reports_symlink_trap_as_error(self, monkeypatch, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        (tmp_path / "evil").symlink_to(real)
        monkeypatch.setattr(vault, "VAULT_DIR", str(tmp_path / "evil" / "vault"))
        legacy = tmp_path / "legacy" / "twitter-auth.env"
        legacy.parent.mkdir()
        legacy.write_text("TWITTER_AUTH_TOKEN=t\n")
        monkeypatch.setitem(vault.LEGACY_PATHS, "twitter", str(legacy))
        rows = vault.migrate()
        tw = next(r for r in rows if r["kind"] == "twitter")
        assert tw["status"].startswith("error")
        assert legacy.exists()  # source untouched on refusal
