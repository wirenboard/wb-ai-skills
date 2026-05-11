#!/bin/bash
# Install wb-cli skills for Claude Code, opencode, or any custom folder.
#
# Usage:
#   ./install-skills.sh claude   [--global | --dest <dir>]   # symlinks SKILL.md
#   ./install-skills.sh opencode [--global | --dest <dir>]   # flat copies with frontmatter rewrite
#   ./install-skills.sh manual    --dest <dir>               # flat copies, no rewrites
#
# Defaults (no flag):
#   claude   -> ./.claude/commands/
#   opencode -> ./.opencode/agents/
#
# --global:
#   claude   -> ~/.claude/commands/
#   opencode -> ~/.config/opencode/agents/
#
# --dest <dir> overrides the destination for any target.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$SCRIPT_DIR/skills"

if [ ! -d "$SKILLS_DIR" ]; then
    echo "error: skills/ directory not found at $SKILLS_DIR" >&2
    exit 1
fi

usage() {
    sed -n '2,18p' "$0"
    exit "${1:-1}"
}

TARGET="${1:-}"; shift || true

DEST=""
GLOBAL=0
while [ $# -gt 0 ]; do
    case "$1" in
        --global) GLOBAL=1 ;;
        --dest)   shift; DEST="${1:-}" ;;
        -h|--help) usage 0 ;;
        *) echo "error: unknown flag '$1'" >&2; usage ;;
    esac
    shift
done

resolve_dest() {
    case "$TARGET" in
        claude)
            [ -n "$DEST" ] && return
            DEST=$([ "$GLOBAL" = 1 ] && echo "$HOME/.claude/commands" || echo "./.claude/commands")
            ;;
        opencode)
            [ -n "$DEST" ] && return
            DEST=$([ "$GLOBAL" = 1 ] && echo "$HOME/.config/opencode/agents" || echo "./.opencode/agents")
            ;;
        manual)
            if [ -z "$DEST" ]; then
                echo "error: 'manual' target requires --dest <dir>" >&2
                exit 2
            fi
            ;;
        ""|-h|--help) usage 0 ;;
        *) echo "error: unknown target '$TARGET'" >&2; usage ;;
    esac
}

resolve_dest
mkdir -p "$DEST"

count=0
for skill_dir in "$SKILLS_DIR"/*/; do
    name="$(basename "$skill_dir")"
    src="$skill_dir/SKILL.md"
    [ -f "$src" ] || continue

    case "$TARGET" in
        claude)
            ln -sf "$(realpath "$src")" "$DEST/$name.md"
            ;;
        opencode)
            # opencode wants flat .md; replace `allowed-tools:` with `mode: primary`
            sed 's/^allowed-tools:.*/mode: primary/' "$src" > "$DEST/$name.md"
            ;;
        manual)
            cp "$src" "$DEST/$name.md"
            ;;
    esac
    count=$((count + 1))
done

mode_desc=$(case "$TARGET" in
    claude) echo "symlinks" ;;
    opencode) echo "copies (opencode frontmatter)" ;;
    manual) echo "copies (verbatim)" ;;
esac)
echo "installed $count skills -> $DEST ($mode_desc)"
