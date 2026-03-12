#!/bin/sh
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
STATE_ROOT="$HOME/.ui-commander"
LOG_FILE="$STATE_ROOT/native-host.log"
PYTHON_HINT_FILE="$STATE_ROOT/python-bin"
mkdir -p "$STATE_ROOT"

resolve_python_bin() {
  if [ -n "${UI_COMMANDER_PYTHON:-}" ] && [ -x "${UI_COMMANDER_PYTHON}" ]; then
    printf '%s\n' "${UI_COMMANDER_PYTHON}"
    return 0
  fi

  if [ -f "$PYTHON_HINT_FILE" ]; then
    PYTHON_FROM_FILE=$(head -n 1 "$PYTHON_HINT_FILE" 2>/dev/null)
    if [ -n "$PYTHON_FROM_FILE" ] && [ -x "$PYTHON_FROM_FILE" ]; then
      printf '%s\n' "$PYTHON_FROM_FILE"
      return 0
    fi
  fi

  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi

  if command -v python >/dev/null 2>&1; then
    command -v python
    return 0
  fi

  for candidate in \
    /opt/homebrew/opt/python@3.11/libexec/bin/python \
    /opt/homebrew/bin/python3 \
    /usr/local/bin/python3 \
    /usr/bin/python3
  do
    if [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  return 1
}

PYTHON_BIN="$(resolve_python_bin)"

if [ ! -x "$PYTHON_BIN" ]; then
  {
    printf '%s native_host_entry missing_python hint_file=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$PYTHON_HINT_FILE"
  } >> "$LOG_FILE"
  exit 1
fi

{
  printf '%s native_host_entry start\n' "$(date '+%Y-%m-%d %H:%M:%S')"
  printf '%s pwd=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$(pwd)"
  printf '%s python=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$PYTHON_BIN"
} >> "$LOG_FILE"
exec "$PYTHON_BIN" "$SCRIPT_DIR/companion.py" native-host 2>> "$LOG_FILE"
