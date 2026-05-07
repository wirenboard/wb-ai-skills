#!/usr/bin/env bash
# Установка wb-ai-integration skills для Claude Code или opencode.
#
# Usage:
#   ./install-skills.sh <flavor> <target> [--global]
#     flavor: bash | mcp
#     target: claude | opencode
#     --global: системно (~/.claude или ~/.config/opencode), иначе в .claude/.opencode текущей директории
#
# Примеры:
#   ./install-skills.sh bash claude --global
#   ./install-skills.sh mcp opencode
#   ./install-skills.sh mcp claude     # в ./.claude/skills/

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
[[ -d "$src" ]] || { echo "Нет директории $src" >&2; exit 1; }

# Скиллы, которые не зависят от наличия MCP (рендер диаграмм, поиск по wiki):
# для mcp-flavor доустанавливаются из bash-набора, чтобы cross-references работали.
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

# Список директорий-источников: основной flavor + (для mcp) общие скиллы из bash/
declare -a sources=()
for d in "$src"/*/; do sources+=("$d"); done
if [[ "$flavor" == "mcp" ]]; then
  for shared in "${SHARED_FROM_BASH[@]}"; do
    [[ -d "$REPO/skills/bash/$shared" ]] && sources+=("$REPO/skills/bash/$shared/")
  done
fi

if [[ "$target" == "claude" ]]; then
  # Claude Code: каталог <skill>/SKILL.md, симлинками
  for d in "${sources[@]}"; do
    name="$(basename "$d")"
    ln -sfn "$d" "$dst/$name"
    echo "linked $dst/$name -> $d"
  done
else
  # opencode: плоский <name>.md, конвертация frontmatter
  for d in "${sources[@]}"; do
    name="$(basename "$d")"
    f="$d/SKILL.md"
    [[ -f "$f" ]] || continue
    # Извлекаем description из исходного frontmatter (первый блок --- ... ---)
    desc="$(awk '/^---$/{c++; next} c==1 && /^description:/ {sub(/^description:[[:space:]]*/, ""); gsub(/^"|"$/, ""); print; exit}' "$f")"
    [[ -n "$desc" ]] || desc="Wiren Board: $name"
    # Тело — всё после второго ---
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
echo "Готово. flavor=$flavor target=$target dst=$dst"
