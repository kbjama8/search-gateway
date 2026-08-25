"""CLI smoke tests for the vault + harden subcommands (mocked, hermetic)."""

from __future__ import annotations

import json

from search_gateway import cli


def _run(argv: list[str]) -> int:
    return cli.main(argv)


class TestVaultCli:
    def test_version(self, capsys):
        assert _run(["version"]) == 0
        out = capsys.readouterr().out.strip()
        assert out == cli.__version__ or out == "0.4.2"

    def test_vault_status(self, monkeypatch, tmp_path, capsys):
        from search_gateway.extract import vault
        monkeypatch.setattr(vault, "VAULT_DIR", str(tmp_path))
        monkeypatch.setattr("search_gateway.config.CREDENTIALS_DIR", "")
        assert _run(["vault", "status"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["persona"] == "kaiser"
        assert out["hygiene"]["ok"] is False  # missing vault → warn

    def test_vault_migrate_dry_run(self, monkeypatch, tmp_path, capsys):
        from search_gateway.extract import vault
        monkeypatch.setattr(vault, "VAULT_DIR", str(tmp_path))
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        (legacy / "twitter-auth.env").write_text("TWITTER_AUTH_TOKEN=t\n")
        monkeypatch.setitem(vault.LEGACY_PATHS, "twitter",
                            str(legacy / "twitter-auth.env"))
        monkeypatch.setitem(vault._CONFIG_PATHS, "twitter",
                            str(tmp_path / "kaiser" / "twitter.env"))
        assert _run(["vault", "migrate", "--dry-run"]) == 0
        rows = json.loads(capsys.readouterr().out)
        assert rows[0]["status"] == "migrated"
        assert (legacy / "twitter-auth.env").exists()  # untouched

    def test_vault_migrate_real(self, monkeypatch, tmp_path, capsys):
        from search_gateway.extract import vault
        monkeypatch.setattr(vault, "VAULT_DIR", str(tmp_path))
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        (legacy / "deepseek.env").write_text("DEEPSEEK_API_KEY=sk-x\n")
        monkeypatch.setitem(vault.LEGACY_PATHS, "deepseek",
                            str(legacy / "deepseek.env"))
        monkeypatch.setitem(vault._CONFIG_PATHS, "deepseek",
                            str(tmp_path / "kaiser" / "deepseek.env"))
        assert _run(["vault", "migrate"]) == 0
        rows = json.loads(capsys.readouterr().out)
        deepseek = next(r for r in rows if r["kind"] == "deepseek")
        assert deepseek["status"] == "migrated"
        assert not (legacy / "deepseek.env").exists()

    def test_harden_install_for_unit(self, monkeypatch, capsys, tmp_path):
        from search_gateway.extract import harden
        monkeypatch.setattr(harden, "STATE_PATH", tmp_path / "harden.json")
        monkeypatch.setattr(harden, "_nft", lambda: "/usr/bin/nft")
        monkeypatch.setattr(harden, "cgroupv2_mounted", lambda: True)
        monkeypatch.setattr(harden, "_run_nft", lambda *a, **k: (0, ""))
        monkeypatch.setattr(harden, "_unit_cgroup_path",
                           lambda unit: f"/u.slice/{unit}")
        assert _run(["harden", "--install", "--sudo", "--for",
                     "search-gateway@8765.service"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["cgroup_path"] == "/u.slice/search-gateway@8765.service"


class TestHardenCli:
    def test_harden_status(self, monkeypatch, capsys):
        from search_gateway.extract import harden
        monkeypatch.setattr(harden, "_run_nft", lambda *a, **k: (127, "no"))
        monkeypatch.setattr(harden, "_nft", lambda: None)
        monkeypatch.setattr(harden, "_load_state", lambda: {})
        assert _run(["harden", "--status"]) == 1  # not installed
        out = json.loads(capsys.readouterr().out)
        assert out["installed"] is False

    def test_harden_check_reports(self, monkeypatch, capsys):
        from search_gateway.extract import harden
        monkeypatch.setattr(harden, "_run_nft", lambda *a, **k: (0, ""))
        monkeypatch.setattr(harden, "_nft", lambda: "/usr/bin/nft")
        monkeypatch.setattr(harden, "systemd_run_available", lambda: True)
        monkeypatch.setattr(harden, "_load_state", lambda: {})
        monkeypatch.setattr(harden, "current_cgroup", lambda: "/u.scope")
        assert _run(["harden", "--check"]) == 0
        captured = capsys.readouterr().out
        assert "enforceability" in captured

    def test_harden_install_dry_run(self, monkeypatch, capsys):
        from search_gateway.extract import harden
        monkeypatch.setattr(harden, "_nft", lambda: "/usr/bin/nft")
        monkeypatch.setattr(harden, "cgroupv2_mounted", lambda: True)
        monkeypatch.setattr(harden, "_scope_cgroup_path", lambda: "/u.scope")
        assert _run(["harden", "--install", "--dry-run", "--sudo"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is True
        assert "table inet sg_egress" in out["rules"]

    def test_harden_install_refuses_without_nft(self, monkeypatch, capsys):
        from search_gateway.extract import harden
        monkeypatch.setattr(harden, "_nft", lambda: None)
        assert _run(["harden", "--install"]) == 1
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is False

    def test_harden_uninstall(self, monkeypatch, capsys):
        from search_gateway.extract import harden
        monkeypatch.setattr(harden, "_run_nft", lambda *a, **k: (0, ""))
        assert _run(["harden", "--uninstall"]) == 0
        assert json.loads(capsys.readouterr().out)["ok"] is True
        monkeypatch.setattr(harden, "_run_nft", lambda *a, **k: (1, "no table"))
        assert _run(["harden", "--uninstall"]) == 1
