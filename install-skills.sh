#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$SCRIPT_DIR/skills"

if [ ! -d "$SKILLS_DIR" ]; then
    echo "error: skills/ directory not found at $SKILLS_DIR" >&2
    exit 1
fi

usage() {
    cat <<'EOF'
Install or uninstall wb-ai-skills for Claude Code, OpenCode, or any other AI agent.

Usage:
  install-skills.sh <target> [options]
  install-skills.sh uninstall <target> [options]

Targets:
  claude    Copy skills to the Claude Code commands directory.
  opencode  Copy skills to the OpenCode agents directory.
            Rewrites frontmatter: allowed-tools -> mode: primary.
  manual    Copy skills to a custom directory (--dest required).
            Strips frontmatter to name + description only — safe for
            any agent that does not know Claude- or OpenCode-specific fields.

Options:
  --global        Use the user-level directory instead of the project-local one:
                    claude   ~/.claude/commands/
                    opencode ~/.config/opencode/agents/
  --dest <dir>    Override the destination directory (works with all targets).
  -h, --help      Show this help and exit.

Default destinations (no --global / --dest):
  claude   ./.claude/commands/
  opencode ./.opencode/agents/

Examples:
  ./install-skills.sh claude                       # project-local Claude Code
  ./install-skills.sh claude --global              # user-wide Claude Code
  ./install-skills.sh opencode --global            # user-wide OpenCode
  ./install-skills.sh manual --dest ~/my-agent/prompts
  ./install-skills.sh uninstall claude --global    # remove user-wide Claude Code skills
EOF
    exit "${1:-0}"
}

ACTION="install"
TARGET="${1:-}"; shift || true

if [ "$TARGET" = "uninstall" ]; then
    ACTION="uninstall"
    TARGET="${1:-}"; shift || true
fi

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

if [ "$ACTION" = "uninstall" ]; then
    count=0
    for src in "$SKILLS_DIR"/*.md; do
        [ -f "$src" ] || continue
        name="$(basename "$src")"
        target="$DEST/$name"
        if [ -e "$target" ] || [ -L "$target" ]; then
            rm -f "$target"
            count=$((count + 1))
        fi
    done
    echo "removed $count skills from $DEST"
    exit 0
fi

mkdir -p "$DEST"

count=0
for src in "$SKILLS_DIR"/*.md; do
    [ -f "$src" ] || continue
    name="$(basename "$src")"

    case "$TARGET" in
        claude)
            rm -f "$DEST/$name"
            cp "$src" "$DEST/$name"
            ;;
        opencode)
            # opencode wants flat .md; replace `allowed-tools:` with `mode: primary`
            sed 's/^allowed-tools:.*/mode: primary/' "$src" > "$DEST/$name"
            ;;
        manual)
            # Strip frontmatter to name+description only (agent-neutral)
            awk '
                BEGIN { in_fm=0; done=0; printed=0 }
                /^---$/ && !done {
                    if (!in_fm) { in_fm=1; print; next }
                    # closing ---: emit minimal frontmatter then the rest
                    print "---"; done=1; in_fm=0; next
                }
                in_fm {
                    if (/^name:/ || /^description:/) print
                    next
                }
                { print }
            ' "$src" > "$DEST/$name"
            ;;
    esac
    count=$((count + 1))
done

mode_desc=$(case "$TARGET" in
    claude) echo "copies" ;;
    opencode) echo "copies (opencode frontmatter)" ;;
    manual) echo "copies (frontmatter: name+description only)" ;;
esac)
echo "installed $count skills -> $DEST ($mode_desc)"
