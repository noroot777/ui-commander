#!/bin/sh
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
STATE_ROOT="$HOME/.screen-commander"
LOG_FILE="$STATE_ROOT/native-host.log"
mkdir -p "$STATE_ROOT"

PYTHON_BIN=/opt/homebrew/opt/python@3.11/libexec/bin/python

if [ ! -x "$PYTHON_BIN" ]; then
  {
    printf '%s native_host_entry missing_python=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$PYTHON_BIN"
  } >> "$LOG_FILE"
  exit 1
fi

{
  printf '%s native_host_entry start\n' "$(date '+%Y-%m-%d %H:%M:%S')"
  printf '%s pwd=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$(pwd)"
  printf '%s python=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$PYTHON_BIN"
} >> "$LOG_FILE"
exec "$PYTHON_BIN" "$SCRIPT_DIR/companion.py" native-host 2>> "$LOG_FILE"
