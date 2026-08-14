#!/usr/bin/env bash
# install.sh — symlink the search-gateway orchestration skills into your agent
# skill directories (OpenCode + Claude Code).
#
# Idempotent: existing links are left alone unless you pass --force.
#
#   ./install.sh            # create links where missing
#   ./install.sh --force    # relink over existing entries
#
# Override the default destinations with:
#   OPENCODE_SKILLS_DIR=/path/to/skills ./install.sh
#   CLAUDE_SKILLS_DIR=/path/to/skills  ./install.sh
#
# `diagram-design` is a git submodule — run `git submodule update --init` first
# if you want it linked too.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_SRC="$SCRIPT_DIR/skills"

# Owned skills (source of truth in this repo) → $SKILLS_SRC/<name>.
OWNED_SKILLS=(deep-research master-router report monitor research-rubric)

# External skills pulled in as git submodules; each entry is name:source-path.
SUBMODULE_SKILLS=(
  "diagram-design:$SCRIPT_DIR/diagram-design/skills/diagram-design"
)

OPENCODE_SKILLS="${OPENCODE_SKILLS_DIR:-$HOME/.config/opencode/skills}"
CLAUDE_SKILLS="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"

FORCE=0
case "${1:-}" in
  --force | -f) FORCE=1 ;;
  "") ;;
  *)
    echo "usage: $0 [--force]" >&2
    exit 2
    ;;
esac

link() {
  local src="$1" link="$2"
  if [ -e "$link" ] || [ -L "$link" ]; then
    if [ "$FORCE" -eq 1 ]; then
      rm -rf "$link"
    else
      echo "skip (exists): $link" >&2
      return
    fi
  fi
  ln -s "$src" "$link"
  echo "linked: $link -> $src"
}

link_into() {
  local dest="$1" name src
  mkdir -p "$dest"
  for name in "${OWNED_SKILLS[@]}"; do
    link "$SKILLS_SRC/$name" "$dest/$name"
  done
  for entry in "${SUBMODULE_SKILLS[@]}"; do
    name="${entry%%:*}"
    src="${entry#*:}"
    if [ -e "$src/SKILL.md" ]; then
      link "$src" "$dest/$name"
    else
      echo "skip (missing submodule — run: git submodule update --init): $name" >&2
    fi
  done
}

link_into "$OPENCODE_SKILLS"
link_into "$CLAUDE_SKILLS"
echo "done."
