#!/usr/bin/env bash
set -euo pipefail

# scripts/setup.sh
# Development setup script for Skald on Linux / macOS.
# Creates core/.venv, sets cache directories, and installs project dependencies.

SCRIPT_DIR="$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -P -- "$SCRIPT_DIR/.." && pwd)"

# 1. Source dev-env to activate project-local caches
# shellcheck source=scripts/dev-env.sh
source "$SCRIPT_DIR/dev-env.sh"

# 2. Check that Python 3.12.x is on PATH
PYTHON_BIN=""
for candidate in python3.12 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    ver="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
    if [ "$ver" = "3.12" ]; then
      PYTHON_BIN="$candidate"
      break
    fi
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  echo "Error: Python 3.12.x was not found on PATH." >&2
  echo "Skald requires Python 3.12.x." >&2
  echo "Please install Python 3.12:" >&2
  echo "  - Linux (apt): sudo apt install python3.12 python3.12-venv" >&2
  echo "  - uv: uv python install 3.12" >&2
  echo "  - Download: https://www.python.org/downloads/" >&2
  exit 1
fi

# Check that Node 22.x or 24.x is on PATH
if ! command -v node >/dev/null 2>&1; then
  echo "Error: Node.js was not found on PATH." >&2
  echo "Skald requires Node.js 22.x or 24.x LTS." >&2
  echo "Please install Node.js from https://nodejs.org/" >&2
  exit 1
fi

NODE_VER="$(node -v 2>/dev/null || true)"
case "$NODE_VER" in
  v22.*|v24.*)
    ;;
  *)
    echo "Error: Node.js version $NODE_VER is not supported." >&2
    echo "Skald requires Node.js 22.x or 24.x LTS." >&2
    echo "Please install Node.js from https://nodejs.org/" >&2
    exit 1
    ;;
esac

# 3. Create core/.venv if missing or broken (must contain working pip)
VENV_DIR="$REPO_ROOT/core/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"

if [ ! -f "$VENV_PYTHON" ] || ! "$VENV_PYTHON" -m pip --version >/dev/null 2>&1; then
  echo "Creating core virtual environment at $VENV_DIR..."
  rm -rf "$VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  if ! "$VENV_PYTHON" -m pip --version >/dev/null 2>&1; then
    echo "Error: core/.venv was created without pip. Please install python3.12-venv (or ensurepip)." >&2
    exit 1
  fi
fi

# 4. Upgrade pip inside core/.venv
echo "Upgrading pip in core/.venv..."
"$VENV_PYTHON" -m pip install --upgrade pip

# 5. If core/pyproject.toml exists, pip install -e "core[dev]"
if [ -f "$REPO_ROOT/core/pyproject.toml" ]; then
  echo "Installing core in editable mode with dev dependencies..."
  (cd "$REPO_ROOT" && "$VENV_PYTHON" -m pip install -e "core[dev]")
fi

# 6. If worker/pyproject.toml exists, pip install -e worker
if [ -f "$REPO_ROOT/worker/pyproject.toml" ]; then
  echo "Installing worker in editable mode..."
  (cd "$REPO_ROOT" && "$VENV_PYTHON" -m pip install -e worker)
fi

# 7. If app/package-lock.json exists, npm ci in app/
if [ -f "$REPO_ROOT/app/package-lock.json" ]; then
  echo "Running npm ci in app/..."
  (cd "$REPO_ROOT/app" && npm ci)
fi

# 8. If scripts/deps.lock.json exists, run scripts/fetch_deps.py
if [ -f "$REPO_ROOT/scripts/deps.lock.json" ]; then
  echo "Fetching pinned dependencies..."
  "$VENV_PYTHON" "$REPO_ROOT/scripts/fetch_deps.py"
fi

echo "Development environment setup complete."
