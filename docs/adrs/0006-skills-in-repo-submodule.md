# 0006: orchestration skills ship in-repo; `diagram-design` is a submodule

**Status: Accepted**

## Context

The gateway's decoupling boundary (`docs/architecture.md#the-decoupling-boundary`)
requires that orchestration logic — `deep-research`, `master-router`,
`report`, `monitor`, `research-rubric` — talk to the gateway only over MCP
tools, never by reading gateway internals directly. But that logic still
needs to be versioned somewhere, installed somehow, and kept in sync with
whatever tool surface the gateway currently exposes. A separate repo per
skill would create a version-matching problem between the gateway's tool
surface and each skill's assumptions about it; a general-purpose diagram
tool (`diagram-design`), by contrast, has its own independent release
cadence and isn't gateway-specific at all.

## Decision

The five orchestration skills ship in-repo, under `skills/`, versioned
alongside the gateway they depend on — install with `./install.sh`, which
symlinks them into the client's skill directory rather than copying, so a
`git pull` on this repo updates the installed skills too.
`diagram-design` — general-purpose, not gateway-specific, used by the
`report` skill's deliverables — arrives as a git submodule instead, keeping
its own commit history and release cadence independent of the gateway's.

## Consequences

- A skill can never silently drift out of sync with the gateway's tool
  surface it was written against — they share one repo, one version, one
  `git log`.
- `install.sh`'s symlink (not copy) means skill updates propagate to an
  installed client automatically on the next `git pull`, without a separate
  reinstall step — but also means the skill files must not be edited in the
  client's skill directory, only in this repo.
- `diagram-design` being a submodule means cloning this repo without
  `--recurse-submodules` leaves that directory empty — a common first-clone
  surprise, worth calling out in `CONTRIBUTING.md`'s setup section.