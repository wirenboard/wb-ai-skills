#!/usr/bin/env bash
# Install wb-ai-integration skills into Claude Code or opencode.
#
# Usage:
#   ./install-skills.sh <flavor> <target> [--global]
#     flavor: bash | mcp
#     target: claude | opencode
#     --global: system-wide (~/.claude or ~/.config/opencode); otherwise into .claude/.opencode of the current dir
#
# Examples:
#   ./install-skills.sh bash claude --global
#   ./install-skills.sh mcp opencode
#   ./install-skills.sh mcp claude     # into ./.claude/skills/

set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"

flavor="${1:-}"
target="${2:-}"
scope="${3:-}"

usage() {
  sed -n '2,11p' "$0" >&2
  exit 1
}

[[ "$flavor" =~ ^(bash|mcp)$ ]] || usage
[[ "$target" =~ ^(claude|opencode)$ ]] || usage

src="$REPO/skills/$flavor"
[[ -d "$src" ]] || { echo "Source dir not found: $src" >&2; exit 1; }

# Skills that don't depend on MCP being present (Mermaid rendering, wiki search):
# for the mcp flavor we additionally install them from the bash set so cross-references resolve.
SHARED_FROM_BASH=(diagrams documentation-search)

if [[ "$scope" == "--global" ]]; then
  case "$target" in
    claude)   dst="$HOME/.claude/skills" ;;
    opencode) dst="$HOME/.config/opencode/agents" ;;
  esac
else
  case "$target" in
    claude)   dst="$PWD/.claude/skills" ;;
    opencode) dst="$PWD/.opencode/agents" ;;
  esac
fi

mkdir -p "$dst"

# Source dirs: primary flavor + (for mcp) the shared bash skills above.
declare -a sources=()
for d in "$src"/*/; do sources+=("$d"); done
if [[ "$flavor" == "mcp" ]]; then
  for shared in "${SHARED_FROM_BASH[@]}"; do
    [[ -d "$REPO/skills/bash/$shared" ]] && sources+=("$REPO/skills/bash/$shared/")
  done
fi

if [[ "$target" == "claude" ]]; then
  # Claude Code: <skill>/SKILL.md directories, installed as symlinks.
  for d in "${sources[@]}"; do
    name="$(basename "$d")"
    ln -sfn "$d" "$dst/$name"
    echo "linked $dst/$name -> $d"
  done
else
  # opencode: flat <name>.md, with frontmatter conversion.
  for d in "${sources[@]}"; do
    name="$(basename "$d")"
    f="$d/SKILL.md"
    [[ -f "$f" ]] || continue
    # Pull description from the source frontmatter (the first --- ... --- block).
    desc="$(awk '/^---$/{c++; next} c==1 && /^description:/ {sub(/^description:[[:space:]]*/, ""); gsub(/^"|"$/, ""); print; exit}' "$f")"
    [[ -n "$desc" ]] || desc="Wiren Board: $name"
    # Body — everything after the second ---.
    body="$(awk 'BEGIN{c=0} /^---$/{c++; next} c>=2{print}' "$f")"
    {
      echo "---"
      echo "description: $desc"
      echo "mode: primary"
      echo "---"
      echo
      echo "$body"
    } > "$dst/$name.md"
    echo "wrote $dst/$name.md"
  done
fi

echo
echo "Done. flavor=$flavor target=$target dst=$dst"
