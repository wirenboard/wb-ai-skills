#!/usr/bin/env bash
# Install wb-ai-skills skills into Claude Code or opencode.
#
# Usage:
#   ./install-skills.sh <target> [--global]
#     target: claude | opencode
#     --global: system-wide (~/.claude or ~/.config/opencode); otherwise into .claude/.opencode of the current dir
#
# Examples:
#   ./install-skills.sh claude --global
#   ./install-skills.sh opencode
#   ./install-skills.sh claude     # into ./.claude/skills/

set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"

target="${1:-}"
scope="${2:-}"

usage() {
  sed -n '2,11p' "$0" >&2
  exit 1
}

[[ "$target" =~ ^(claude|opencode)$ ]] || usage

src="$REPO/skills/bash"
[[ -d "$src" ]] || { echo "Source dir not found: $src" >&2; exit 1; }

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

declare -a sources=()
for d in "$src"/*/; do sources+=("$d"); done

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
echo "Done. target=$target dst=$dst"
