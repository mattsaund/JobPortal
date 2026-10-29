#!/usr/bin/env bash
# Start JobPortal on macOS or Linux. The first run creates a virtual environment in .venv and installs JobPortal into it.
#   ./run.sh                 open the app (its own window, or your browser if no window toolkit is available)
#   ./run.sh --browser       open it in your browser
#   ./run.sh --doctor        check that everything JobPortal needs is installed
# Any other option is passed to `jobportal` (see ./run.sh --help).
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in python3 python3.14 python3.13 python3.12 python3.11; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then PY="$c"; break; fi
  done
fi
[ -n "$PY" ] || { echo "JobPortal needs Python 3.11 or newer: https://www.python.org/downloads/"; exit 1; }

if [ ! -x .venv/bin/python ]; then
  echo "Creating the Python environment in .venv ..."
  EXTRA=""
  # Linux: reuse the system's GTK WebKit bindings (when installed) so JobPortal gets a window of its own.
  if [ "$(uname)" = "Linux" ] && "$PY" -c "import gi; gi.require_version('WebKit2', '4.1')" 2>/dev/null; then EXTRA="--system-site-packages"; fi
  "$PY" -m venv $EXTRA .venv
fi

STAMP=.venv/.jobportal-installed
if [ ! -f "$STAMP" ] || [ pyproject.toml -nt "$STAMP" ]; then
  echo "Installing JobPortal and its dependencies ..."
  .venv/bin/python -m pip install -q --upgrade pip
  .venv/bin/python -m pip install -q -e .
  touch "$STAMP"
fi
exec .venv/bin/python -m jobportal "$@"
