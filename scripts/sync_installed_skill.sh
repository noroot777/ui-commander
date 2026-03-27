#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dest="${1:-$HOME/.codex/skills/ui-commander}"

if [[ ! -d "$dest" ]]; then
  echo "Installed skill directory not found: $dest" >&2
  exit 1
fi

if [[ "$(cd "$dest" && pwd)" == "$repo_root" ]]; then
  echo "Installed skill directory already points at this workspace."
  exit 0
fi

rsync -a \
  --exclude ".git/" \
  --exclude ".DS_Store" \
  --exclude "__pycache__/" \
  --exclude "*.pyc" \
  --exclude ".ui-commander/" \
  --exclude ".venv/" \
  "$repo_root/" "$dest/"

echo "Synced workspace to installed skill:"
echo "  source: $repo_root"
echo "  dest:   $dest"
