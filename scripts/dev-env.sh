# scripts/dev-env.sh
# Export cache environment variables for project-local development in Skald.
# Must be sourced: source scripts/dev-env.sh (or . scripts/dev-env.sh).

# Guard against accidental execution instead of sourcing
if [ -n "${BASH_SOURCE[0]:-}" ] && [ "${BASH_SOURCE[0]}" = "$0" ]; then
  echo "scripts/dev-env.sh: script must be sourced into your shell, not run directly." >&2
  echo "Usage: source scripts/dev-env.sh" >&2
  exit 1 2>/dev/null || return 1 2>/dev/null || true
fi

# Determine script path portably (bash, zsh, sh)
_SKALD_DEV_ENV_SCRIPT="${BASH_SOURCE[0]:-${(%):-%x}}"
if [ -z "$_SKALD_DEV_ENV_SCRIPT" ]; then
  _SKALD_DEV_ENV_SCRIPT="$0"
fi

_SKALD_SCRIPTS_DIR="$(cd -P -- "$(dirname -- "$_SKALD_DEV_ENV_SCRIPT")" 2>/dev/null && pwd)"
if [ -z "$_SKALD_SCRIPTS_DIR" ]; then
  echo "scripts/dev-env.sh: failed to resolve scripts directory" >&2
  return 1 2>/dev/null || true
fi

_SKALD_REPO_ROOT="$(cd -P -- "$_SKALD_SCRIPTS_DIR/.." 2>/dev/null && pwd)"
if [ -z "$_SKALD_REPO_ROOT" ]; then
  echo "scripts/dev-env.sh: failed to resolve repository root" >&2
  return 1 2>/dev/null || true
fi

mkdir -p "$_SKALD_REPO_ROOT/.cache/pip" \
         "$_SKALD_REPO_ROOT/.cache/uv" \
         "$_SKALD_REPO_ROOT/.cache/npm" \
         "$_SKALD_REPO_ROOT/.cache/electron" \
         "$_SKALD_REPO_ROOT/.cache/electron-builder" \
         "$_SKALD_REPO_ROOT/.cache/devdata" \
         "$_SKALD_REPO_ROOT/vendor"

export PIP_CACHE_DIR="$_SKALD_REPO_ROOT/.cache/pip"
export UV_CACHE_DIR="$_SKALD_REPO_ROOT/.cache/uv"
export npm_config_cache="$_SKALD_REPO_ROOT/.cache/npm"
export ELECTRON_CACHE="$_SKALD_REPO_ROOT/.cache/electron"
export ELECTRON_BUILDER_CACHE="$_SKALD_REPO_ROOT/.cache/electron-builder"
export SKALD_DEV_DATA="$_SKALD_REPO_ROOT/.cache/devdata"
export SKALD_VENDOR="$_SKALD_REPO_ROOT/vendor"

unset _SKALD_DEV_ENV_SCRIPT _SKALD_SCRIPTS_DIR _SKALD_REPO_ROOT
