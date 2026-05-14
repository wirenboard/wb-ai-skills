#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$SCRIPT_DIR/wb-plc/skills"

if [ ! -d "$SKILLS_DIR" ]; then
    echo "error: skills directory not found at $SKILLS_DIR" >&2
    exit 1
fi

usage() {
    cat <<'EOF'
Install or uninstall wb-ai-skills for Claude Code, OpenCode, or any other AI
agent.

When possible, prefer the marketplace path instead of this script:

  /plugin marketplace add wirenboard/wb-ai-skills
  /plugin install wb-plc@wb-ai-skills

It works for Claude Code and GitHub Copilot CLI out of the box. This script
exists for agents without marketplace support (older Claude Code, OpenCode,
miscellaneous LLM agents).

Usage:
  install-skills.sh <target> [options]
  install-skills.sh uninstall <target> [options]

Targets:
  claude    Copy each skill directory (SKILL.md + references/ + scripts/) to
            the Claude Code skills directory. Preserves the native skill
            layout with all supporting files.
  opencode  Extract each SKILL.md to a flat <name>.md in the OpenCode agents
            directory. Rewrites frontmatter: allowed-tools -> mode: primary.
            Side files (references/, scripts/) are NOT copied — they only
            make sense in agents that read skills as directories.
  manual    Extract each SKILL.md to a flat <name>.md in --dest. Strips
            frontmatter to name + description only — safe for any agent that
            does not know Claude- or OpenCode-specific fields.

Options:
  --global        Use the user-level directory instead of the project-local one:
                    claude   ~/.claude/skills/
                    opencode ~/.config/opencode/agents/
  --dest <dir>    Override the destination directory (works with all targets).
  -h, --help      Show this help and exit.

Default destinations (no --global / --dest):
  claude   ./.claude/skills/
  opencode ./.opencode/agents/

Examples:
  ./install-skills.sh claude                       # project-local Claude Code
  ./install-skills.sh claude --global              # user-wide Claude Code
  ./install-skills.sh opencode --global            # user-wide OpenCode
  ./install-skills.sh manual --dest ~/my-agent/prompts
  ./install-skills.sh uninstall claude --global    # remove user-wide skills
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
            DEST=$([ "$GLOBAL" = 1 ] && echo "$HOME/.claude/skills" || echo "./.claude/skills")
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

# List skill names (subdirectory names under wb-plc/skills/ that contain SKILL.md).
list_skills() {
    for dir in "$SKILLS_DIR"/*/; do
        [ -d "$dir" ] || continue
        [ -f "${dir}SKILL.md" ] || continue
        basename "$dir"
    done
}

if [ "$ACTION" = "uninstall" ]; then
    count=0
    while IFS= read -r name; do
        case "$TARGET" in
            claude)
                target="$DEST/$name"
                ;;
            opencode|manual)
                target="$DEST/$name.md"
                ;;
        esac
        if [ -e "$target" ] || [ -L "$target" ]; then
            rm -rf "$target"
            count=$((count + 1))
        fi
    done < <(list_skills)
    echo "removed $count skills from $DEST"
    exit 0
fi

mkdir -p "$DEST"

count=0
while IFS= read -r name; do
    src_dir="$SKILLS_DIR/$name"
    src_skill="$src_dir/SKILL.md"

    case "$TARGET" in
        claude)
            # Copy the whole skill directory (SKILL.md + references/ + scripts/ + ...)
            target_dir="$DEST/$name"
            rm -rf "$target_dir"
            cp -r "$src_dir" "$target_dir"
            ;;
        opencode)
            # OpenCode wants a flat .md per agent; rewrite frontmatter.
            sed 's/^allowed-tools:.*/mode: primary/' "$src_skill" > "$DEST/$name.md"
            ;;
        manual)
            # Strip frontmatter to name+description only (agent-neutral).
            awk '
                BEGIN { in_fm=0; done=0 }
                /^---$/ && !done {
                    if (!in_fm) { in_fm=1; print; next }
                    print "---"; done=1; in_fm=0; next
                }
                in_fm {
                    if (/^name:/ || /^description:/) print
                    next
                }
                { print }
            ' "$src_skill" > "$DEST/$name.md"
            ;;
    esac
    count=$((count + 1))
done < <(list_skills)

mode_desc=$(case "$TARGET" in
    claude) echo "directories with SKILL.md + side files" ;;
    opencode) echo "flat .md with opencode frontmatter" ;;
    manual) echo "flat .md with frontmatter trimmed to name+description" ;;
esac)
echo "installed $count skills -> $DEST ($mode_desc)"
