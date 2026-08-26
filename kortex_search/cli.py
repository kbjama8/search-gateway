"""Console entry point: `kortex-search serve|doctor|check|version|warm`."""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
from collections.abc import Sequence

from . import __version__, health
from .config import MCP_HOST, MCP_PORT
from .log import configure_logging


def _cmd_serve(args: argparse.Namespace) -> int:
    from .server import main

    def _graceful(_signum, _frame):
        raise KeyboardInterrupt

    # Map SIGTERM (systemd stop) to the same clean unwind FastMCP uses for
    # SIGINT, so the running loop cancels tasks and exits without corruption.
    signal.signal(signal.SIGTERM, _graceful)

    # `--transport/--host/--port` live on the `serve` subparser, so the bare
    # `kortex-search` command (no subcommand) — which also routes here — does
    # not have them. Fall back to defaults.
    transport = getattr(args, "transport", "stdio")
    if transport in ("http", "sse"):
        main(transport=transport,
             host=getattr(args, "host", MCP_HOST),
             port=getattr(args, "port", MCP_PORT))
    else:
        main()
    return 0


def _cmd_doctor(_args: argparse.Namespace) -> int:
    report = asyncio.run(health.report())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("redis", {}).get("ok") else 1


def _cmd_check(_args: argparse.Namespace) -> int:
    ok, report = asyncio.run(health.check())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report.get("llm", {}).get("available"):
        print("warning: DEEPSEEK_API_KEY not set — answer synthesis disabled",
              file=sys.stderr)
    return 0 if ok else 1


def _cmd_version(_args: argparse.Namespace) -> int:
    print(__version__)
    return 0


def _cmd_vault(args: argparse.Namespace) -> int:
    from .extract import vault

    if args.vault_command == "migrate":
        rows = vault.migrate(dry_run=args.dry_run)
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0 if all(r["status"] in ("noop", "migrated", "empty")
                        for r in rows) else 1
    # status
    print(json.dumps(vault.status(), ensure_ascii=False, indent=2))
    return 0


def _cmd_harden(args: argparse.Namespace) -> int:
    from .extract import harden

    if args.harden_action == "install":
        out = harden.install(sudo=args.sudo, dry_run=args.dry_run,
                             for_unit=args.for_unit)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("ok") else 1
    if args.harden_action == "uninstall":
        out = harden.uninstall()
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("ok") else 1
    if args.harden_action == "mark-installed":
        # receipt for a successful privileged load (the unprivileged gateway
        # cannot probe the kernel table — the loader's success is the proof)
        out = harden.mark_installed()
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("ok") else 1
    st = harden.status()
    print(json.dumps(st, ensure_ascii=False, indent=2))
    if args.harden_action == "check":
        # `check` reports enforceability (exit 0 even when not enforced —
        # the unit logs the report; in-process enforce() is the real gate)
        enforceable = st["installed"] and st["systemd_run"]
        detail = "; ".join(st["problems"]) or "permissive"
        print(f"browser-tier enforceability: "
              f"{'yes' if enforceable else 'no — ' + detail}")
        return 0
    return 0 if st["installed"] else 1


def _cmd_warm(_args: argparse.Namespace) -> int:
    from . import embeddings, rerank

    rerank._get_model()          # same-package preload (private, intentional)
    embeddings._get_model()      # same-package preload (private, intentional)
    print(json.dumps({"rerank": rerank.status(), "embed": embeddings.status()},
                     ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kortex-search",
        description="Unified web-search & research MCP server.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="run the MCP server (default: stdio)")
    serve.add_argument("--transport", choices=["stdio", "http", "sse"],
                       default="stdio", help="stdio (default) | http | sse")
    serve.add_argument("--host", default=MCP_HOST,
                       help=f"bind host for http/sse (default: {MCP_HOST})")
    serve.add_argument("--port", type=int, default=MCP_PORT,
                       help=f"bind port for http/sse (default: {MCP_PORT})")
    sub.add_parser("doctor", help="print the full health report as JSON")
    sub.add_parser("check", help="gate: 18 sources + Redis reachable (non-zero on failure)")
    sub.add_parser("version", help="print the package version")
    sub.add_parser("warm", help="preload the rerank + embed models")
    vault = sub.add_parser("vault", help="per-persona secrets vault management")
    vsub = vault.add_subparsers(dest="vault_command")
    vmigrate = vsub.add_parser("migrate",
                               help="move legacy flat env files into the persona vault (D7.3)")
    vmigrate.add_argument("--dry-run", action="store_true",
                          help="report what would move without touching files")
    vsub.add_parser("status", help="vault layout + hygiene findings")
    harden = sub.add_parser("harden", help="L3 kernel egress filter (nftables cgroupv2)")
    harden.add_argument("--install", dest="harden_action", action="store_const",
                        const="install", help="install the egress filter (derive "
                        "the cgroup from the current process; run inside the "
                        "scope or the unit — see docs/deployment.md)")
    harden.add_argument("--dry-run", action="store_true",
                        help="print the ruleset without touching the kernel")
    harden.add_argument("--status", dest="harden_action", action="store_const",
                        const="status", help="report install/coverage state")
    harden.add_argument("--uninstall", dest="harden_action", action="store_const",
                        const="uninstall", help="delete the ks_egress table")
    harden.add_argument("--check", dest="harden_action", action="store_const",
                        const="check", help="report browser-tier enforceability")
    harden.add_argument("--mark-installed", dest="harden_action",
                        action="store_const", const="mark-installed",
                        help="record a successful privileged load (run after "
                             "'sudo nft -f' — the unprivileged probe cannot "
                             "read the kernel table)")
    harden.add_argument("--for", dest="for_unit", metavar="UNIT",
                        default=None,
                        help="target a running user unit's cgroup instead of "
                             "the ks-egress wrapper scope (companion-loader "
                             "deployments)")
    harden.add_argument("--sudo", action="store_true",
                        help="load the ruleset with elevation (root already: "
                        "auto); without it, rules are written for manual load")
    harden.set_defaults(harden_action="status", for_unit=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    handlers = {
        "serve": _cmd_serve,
        "doctor": _cmd_doctor,
        "check": _cmd_check,
        "version": _cmd_version,
        "warm": _cmd_warm,
        "vault": _cmd_vault,
        "harden": _cmd_harden,
    }
    return handlers[args.command or "serve"](args)


if __name__ == "__main__":
    sys.exit(main())
