#!/bin/bash
# Install wb-cli skills for Claude Code or opencode.
#
# Usage:
#   ./install-skills.sh claude [--global]
#   ./install-skills.sh opencode [--global]
#
# Claude:  symlinks SKILL.md files to ~/.claude/commands/ (--global)
#          or ./.claude/commands/ (default)
# opencode: copies as flat .md files to ~/.config/opencode/agents/ (--global)
#           or ./.opencode/agents/ (default)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$SCRIPT_DIR/skills"

if [ ! -d "$SKILLS_DIR" ]; then
    echo "error: skills/ directory not found at $SKILLS_DIR" >&2
    exit 1
fi

TARGET="${1:-}"
GLOBAL="${2:-}"

case "$TARGET" in
    claude)
        if [ "$GLOBAL" = "--global" ]; then
            DEST="$HOME/.claude/commands"
        else
            DEST="./.claude/commands"
        fi
        mkdir -p "$DEST"
        count=0
        for skill_dir in "$SKILLS_DIR"/*/; do
            name="$(basename "$skill_dir")"
            src="$skill_dir/SKILL.md"
            [ -f "$src" ] || continue
            ln -sf "$(realpath "$src")" "$DEST/$name.md"
            count=$((count + 1))
        done
        echo "installed $count skills -> $DEST (symlinks)"
        ;;

    opencode)
        if [ "$GLOBAL" = "--global" ]; then
            DEST="$HOME/.config/opencode/agents"
        else
            DEST="./.opencode/agents"
        fi
        mkdir -p "$DEST"
        count=0
        for skill_dir in "$SKILLS_DIR"/*/; do
            name="$(basename "$skill_dir")"
            src="$skill_dir/SKILL.md"
            [ -f "$src" ] || continue
            # opencode wants flat .md with description in frontmatter
            sed 's/^allowed-tools:.*/mode: primary/' "$src" > "$DEST/$name.md"
            count=$((count + 1))
        done
        echo "installed $count skills -> $DEST (copies)"
        ;;

    *)
        echo "usage: $0 <claude|opencode> [--global]" >&2
        exit 1
        ;;
esac
