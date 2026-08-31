"""Per-persona secrets vault under `~/.agent-reach/profiles/<persona>/`.

Doctrine (LESSONS.md §1.5): env vars are NOT suitable for secrets — files
with 0600 modes are. This module is the single authority on where each
secret file lives and whether it is healthy.

Resolution order for every env-file kind:
  1. `KORTEX_SEARCH_CREDENTIALS_DIR` (systemd `$CREDENTIALS_DIRECTORY`
     bridge — files named `<kind>.env` arrive from `LoadCredential=`)
  2. the configured vault path (defaults in config.py)

Legacy flat paths (`~/.agent-reach/<name>.env`) were honored through 0.4.2
and REMOVED in 0.4.3 (decision D7.3). `migrate()` still reads them as the
migration *source* — machines that never migrated must run `kortex-search
vault migrate` before upgrading past 0.4.2.

`hygiene()` is warn-not-fail (degradation doctrine) — but the doctor section
it feeds colors the findings red so an operator never misses them.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import config as _config
from ..config import (
    DEEPSEEK_ENV_FILE,
    PERSONA,
    PROXY_ENV_FILE,
    TWITTER_ENV_FILE,
    VAULT_DIR,
    load_env_file,
)

logger = logging.getLogger("kortex_search.extract.vault")

# Legacy flat paths — migration SOURCE ONLY since 0.4.3 (runtime fallback
# removed per D7.3). Kept so `migrate()` can rescue never-migrated machines.
LEGACY_PATHS: dict[str, str] = {
    "twitter": os.path.expanduser("~/.agent-reach/twitter-auth.env"),
    "deepseek": os.path.expanduser("~/.agent-reach/deepseek.env"),
    "proxy": os.path.expanduser("~/.agent-reach/proxy.env"),
}

# Which keys may live in each vault file — the migration copies only these
# (a secret file never carries leftovers from another persona/service).
_KEYS: dict[str, set[str]] = {
    "twitter": {"TWITTER_AUTH_TOKEN", "TWITTER_CT0"},
    "deepseek": {"DEEPSEEK_API_KEY"},
    "proxy": {"KORTEX_SEARCH_PROXY_USERNAME",
              "KORTEX_SEARCH_PROXY_PASSWORD",
              "KORTEX_SEARCH_PROXY_GATEWAY"},
}

_CONFIG_PATHS: dict[str, str] = {
    "twitter": TWITTER_ENV_FILE,
    "deepseek": DEEPSEEK_ENV_FILE,
    "proxy": PROXY_ENV_FILE,
}

_STALE_DAYS = 90


@dataclass(frozen=True)
class Finding:
    """One hygiene finding. `severity`: ok | warn | error (doctor colors it)."""

    severity: str
    kind: str      # mode | symlink | stale | out-of-vault
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "kind": self.kind,
                "path": self.path, "message": self.message}


def vault_root() -> Path:
    return Path(VAULT_DIR).expanduser()


def profile_dir(persona: str | None = None) -> Path:
    return vault_root() / (persona or PERSONA)


def _vault_path(kind: str, persona: str | None = None) -> Path:
    return profile_dir(persona) / f"{kind}.env"


def env_file_for(kind: str) -> str:
    """Effective env-file path for a secret kind: the configured vault path.

    Since 0.4.3 the legacy flat paths are no longer a runtime fallback
    (D7.3); a missing file simply means the secret is absent — callers
    degrade explicitly.
    """
    return str(Path(_CONFIG_PATHS.get(kind, "")).expanduser())


def load_secrets(kind: str, keys: set[str]) -> dict[str, str]:
    """Read a secret kind through the resolution chain:
    credentials-dir bridge → vault path."""
    path = env_file_for(kind)
    return _config.load_env_file_credential(kind, keys, fallback_path=path)


def list_profiles() -> list[dict[str, Any]]:
    """Vault profile dirs + their files (names only — never the contents)."""
    root = vault_root()
    if not root.exists():
        return []
    out: list[dict[str, Any]] = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        files = sorted(p.name for p in d.iterdir() if p.is_file())
        out.append({"persona": d.name, "files": files})
    return out


def _safe_mkdir(path: Path) -> None:
    """mkdir -p refusing symlinked path components (TOCTOU/escape defense —
    a symlink swap between check and write would land secrets outside the
    vault)."""
    comps = [p for p in path.parents if p != Path(p.anchor)] + [path]
    for comp in reversed(comps):
        if comp.is_symlink():
            raise OSError(f"refusing symlink component: {comp}")
    path.mkdir(parents=True, exist_ok=True)


def _atomic_write_0600(path: Path, content: str) -> None:
    """Write 0600 via O_EXCL + O_NOFOLLOW: no symlink following, no
    clobbering a pre-existing target planted by an attacker."""
    fd = -1
    try:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            path.unlink()  # safe: O_NOFOLLOW-verified regular file or absent
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fd = -1  # ownership passed to the file object
            fh.write(content)
    finally:
        if fd >= 0:
            os.close(fd)


def migrate(dry_run: bool = False) -> list[dict[str, str]]:
    """Move legacy flat env files into the persona vault (D7.3).

    Copies only the declared keys per kind, writes the vault file 0600,
    and (unless dry-run) removes the legacy file. Returns one row per kind:
    {kind, status, old, new}. Never raises — each kind is attempted
    independently so a partial migration reports, not crashes.
    """
    rows: list[dict[str, str]] = []
    for kind in ("twitter", "deepseek", "proxy"):
        legacy = Path(LEGACY_PATHS[kind]).expanduser()
        row = {"kind": kind, "status": "noop", "old": "", "new": ""}
        if not legacy.exists():
            rows.append(row)
            continue
        row["old"] = str(legacy)
        row["new"] = str(_vault_path(kind))
        secrets = load_env_file(str(legacy), _KEYS[kind])
        if not secrets:
            row["status"] = "empty"
            rows.append(row)
            continue
        target = profile_dir()
        try:
            root = vault_root()
            _safe_mkdir(root)
            os.chmod(root, 0o700)
            _safe_mkdir(target)
            os.chmod(target, 0o700)
            out_path = _vault_path(kind)
            if not dry_run:
                body = "".join(f"{k}={v}\n" for k, v in sorted(secrets.items()))
                tmp = out_path.with_suffix(".tmp")
                _atomic_write_0600(tmp, body)
                tmp.replace(out_path)
                os.chmod(out_path, 0o600)
                legacy.unlink()
                logger.info("vault: migrated %s -> %s", legacy, out_path)
            row["status"] = "migrated"
        except OSError as exc:
            row["status"] = f"error: {exc}"
            logger.warning("vault: migration failed for %s: %s", kind, exc)
        rows.append(row)
    return rows


def hygiene() -> list[Finding]:
    """Filesystem + config hygiene checks. Warn-not-fail, but the findings
    surface as red in doctor. Checks: mode enforcement, symlink traps,
    stale files (>90d), out-of-vault `*_AUTH_FILE` config values."""
    findings: list[Finding] = []
    root = vault_root()

    # out-of-vault configured env-file vars (the file exists elsewhere)
    for kind, path in _CONFIG_PATHS.items():
        p = Path(path).expanduser()
        if p.exists() and not p.is_relative_to(root):
            findings.append(Finding(
                "error", "out-of-vault", str(p),
                f"{kind} env file configured outside the vault — migrate it"))

    if not root.exists():
        findings.append(Finding(
            "warn", "missing", str(root),
            "vault dir does not exist (run 'kortex-search vault migrate')"))
        return findings

    if root.is_symlink():
        findings.append(Finding(
            "error", "symlink", str(root),
            "vault root is a symlink — refusing to trust it"))
    elif (root.stat().st_mode & 0o077) != 0:
        findings.append(Finding(
            "warn", "mode", str(root),
            f"vault root mode {oct(root.stat().st_mode & 0o777)} — want 0o700"))

    now = time.time()
    for profile in root.iterdir() if root.is_dir() else []:
        if not profile.is_dir():
            continue
        for path in profile.rglob("*"):
            if not path.is_file():
                continue
            if path.is_symlink():
                target = path.resolve()
                if not target.is_relative_to(root):
                    findings.append(Finding(
                        "error", "symlink", str(path),
                        f"symlink escapes the vault → {target}"))
                continue
            mode = path.stat().st_mode & 0o777
            if mode != 0o600:
                findings.append(Finding(
                    "error", "mode", str(path),
                    f"mode {oct(mode)} — want 0o600"))
            try:
                age_days = (now - path.stat().st_mtime) / 86400
            except OSError as exc:
                findings.append(Finding(
                    "warn", "stat", str(path), f"unreadable stat: {exc}"))
                continue
            if age_days > _STALE_DAYS:
                findings.append(Finding(
                    "warn", "stale", str(path),
                    f"unchanged for {int(age_days)}d — rotate or remove"))
    return findings


def status() -> dict:
    """Doctor section: layout + hygiene findings."""
    findings = hygiene()
    return {
        "persona": PERSONA,
        "vault_dir": str(vault_root()),
        "credentials_dir": _config.CREDENTIALS_DIR or None,
        "profiles": list_profiles(),
        "hygiene": {
            "ok": not any(f.severity in ("warn", "error") for f in findings),
            "findings": [f.as_dict() for f in findings],
        },
    }
