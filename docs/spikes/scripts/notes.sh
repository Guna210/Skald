#!/usr/bin/env bash
# Spike T03.4, round 2: re-measures the side observations quoted in engine-packs.md and prints the raw output.
# Usage (Linux, from the repo root):  bash docs/spikes/scripts/notes.sh <empty work folder> [cu12] > results/cloud-linux-notes.txt 2>&1
set -uo pipefail
WORK=$(realpath "$1"); mkdir -p "$WORK"
HERE=docs/spikes/scripts
UV=vendor/uv/linux64/uv; PY=vendor/python/linux64/bin/python3
for v in $(env | grep -o '^UV_[A-Z_]*'); do unset "$v"; done
export UV_NO_CONFIG=1 UV_NO_PROGRESS=1 UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=hardlink UV_SYSTEM_CERTS=1
export UV_CACHE_DIR="$WORK/uv-cache" UV_PYTHON_INSTALL_DIR="$WORK/python"
PYTORCH=https://download.pytorch.org/whl; PYPI=https://pypi.org/simple
BASE=(--only-binary :all: --python-version 3.12 --python-platform x86_64-manylinux_2_28 --emit-index-annotation --no-header)
COMMON=("${BASE[@]}" --exclude-newer 2026-11-13T00:00:00Z)
h() { printf '\n===== %s =====\n' "$*"; }
pins() { grep -A1 -E "^($1)==" "$2" | grep -v '^--' | paste - - ; }

h "date / uv"; date -u +%FT%TZ; $UV --version

h "1. vendored tool sizes (du -sm, MB)"; du -sm vendor/python/linux64 vendor/uv/linux64

echo; echo "Note: uv searches --extra-index-url BEFORE --index-url, and stops at the first index that has the package name."
h "2a. index attempt: --index-url pytorch/cu126 --extra-index-url pypi  (PyPI searched first; requirements: torch==2.14.1, numpy)"
$UV pip compile $HERE/torch-cu12/requirements.in "${COMMON[@]}" --index-url $PYTORCH/cu126 --extra-index-url $PYPI -q -o "$WORK/a.txt"; echo "rc=$?"
pins 'torch|filelock|setuptools|nvidia-cublas[a-z0-9-]*|nvidia-cuda-runtime[a-z0-9-]*|cuda-toolkit' "$WORK/a.txt"
echo "pins per index:"; grep -o 'from https://[^ ]*' "$WORK/a.txt" | sort | uniq -c

h "2b. index attempt: --index-url pypi --extra-index-url pytorch/cu126  (PyTorch index searched first), with --exclude-newer"
$UV pip compile $HERE/torch-cu12/requirements.in "${COMMON[@]}" --index-url $PYPI --extra-index-url $PYTORCH/cu126 -q -o "$WORK/b.txt" 2>&1 | cut -c1-400; echo "rc=${PIPESTATUS[0]}"
h "2b2. as 2b without --exclude-newer"
$UV pip compile $HERE/torch-cu12/requirements.in "${BASE[@]}" --index-url $PYPI --extra-index-url $PYTORCH/cu126 -q -o "$WORK/b2.txt" 2>&1 | cut -c1-400; echo "rc=${PIPESTATUS[0]}"
h "2b3. as 2b2 with torch==2.14.1+cu126"
printf 'torch==2.14.1+cu126\nnumpy\n' > "$WORK/c.in"
$UV pip compile "$WORK/c.in" "${BASE[@]}" --index-url $PYPI --extra-index-url $PYTORCH/cu126 -q -o "$WORK/b3.txt" 2>&1 | cut -c1-400; echo "rc=${PIPESTATUS[0]}"
if [ -f "$WORK/b3.txt" ]; then pins 'torch|filelock|setuptools|numpy|networkx' "$WORK/b3.txt"; echo "pins per index:"; grep -o 'from https://[^ ]*' "$WORK/b3.txt" | sort | uniq -c; fi

h "2b4. CPU sample, PyTorch index searched first (--index-url pypi --extra-index-url pytorch/cpu), without --exclude-newer"
$UV pip compile $HERE/torch-cpu/requirements.in "${BASE[@]}" --index-url $PYPI --extra-index-url $PYTORCH/cpu -q -o "$WORK/b4.txt" 2>&1 | cut -c1-400; echo "rc=${PIPESTATUS[0]}"
pins 'torch|filelock|setuptools|numpy|networkx' "$WORK/b4.txt"; echo "pins per index:"; grep -o 'from https://[^ ]*' "$WORK/b4.txt" | sort | uniq -c

h "2c. index attempt: as 2a (PyPI first) but torch==2.14.1+cu126"
$UV pip compile "$WORK/c.in" "${COMMON[@]}" --index-url $PYTORCH/cu126 --extra-index-url $PYPI -q -o "$WORK/c.txt" 2>&1 | cut -c1-600; echo "rc=${PIPESTATUS[0]}"

h "2d. --torch-backend cu126 (the committed lock's command)"
$UV pip compile $HERE/torch-cu12/requirements.in "${COMMON[@]}" --torch-backend cu126 -q -o "$WORK/d.txt"; echo "rc=$?"
pins 'torch|triton|filelock|setuptools' "$WORK/d.txt"
echo "pins per index:"; grep -o 'from https://[^ ]*' "$WORK/d.txt" | sort | uniq -c

h "2e. pins per index in the four committed locks"
for f in $HERE/torch-*/locks/*.txt; do echo "$f"; grep -o 'from https://[^ ]*' "$f" | sort | uniq -c; echo "  nvidia-*/cuda-* pins: $(grep -cE '^(nvidia-|cuda-)' "$f")  all pins: $(grep -cE '^[a-z0-9-]+==' "$f")"; done

h "3. PyTorch index listings: cp312 torch wheels per backend (version, platforms)"
for be in cpu cu126 cu128 cu129 cu130 cu132 cu134; do
  curl -sS -o "$WORK/idx.html" -w "$be: HTTP %{http_code}\n" "$PYTORCH/$be/torch/"
  grep -o 'torch-[0-9][^"<]*cp312-cp312-[a-z0-9_]*\.whl' "$WORK/idx.html" | grep -v dev | sed -E 's/torch-([0-9.]+)((%2B|\+)[a-z0-9]+)?-cp312-cp312-(.*)\.whl/\1 \4/' | sort -uV > "$WORK/idx.txt"
  echo "    release versions: $(cut -d' ' -f1 "$WORK/idx.txt" | uniq | tr '\n' ' ')"
  last=$(tail -1 "$WORK/idx.txt" | cut -d' ' -f1); echo "    platforms of $last: $(grep "^$last " "$WORK/idx.txt" | cut -d' ' -f2 | tr '\n' ' ')"
done

h "4. UV_NATIVE_TLS=1 (old variable name) with UV_SYSTEM_CERTS unset"
env -u UV_SYSTEM_CERTS UV_NATIVE_TLS=1 SSL_CERT_FILE="${SSL_CERT_FILE:-}" $UV pip compile $HERE/torch-cpu/requirements.in "${COMMON[@]}" --torch-backend cpu -o "$WORK/e.txt" 2>&1 | grep -iv '^[a-z0-9-]*==\|^    ' | head -5; echo "rc=${PIPESTATUS[0]}"

sync_cold() {  # $1 = cpu|cu12, $2 = backend
  local pack="$WORK/pack-$1"
  UV_CACHE_DIR="$WORK/uv-cache-$1" $UV venv -q --python $PY --no-project "$pack"
  UV_CACHE_DIR="$WORK/uv-cache-$1" $UV pip sync --python "$pack/bin/python" --require-hashes --no-build --torch-backend "$2" \
    $HERE/torch-$1/locks/linux-$1.txt 2>&1 | grep -E '^(Downloading| Downloaded|Prepared|Installed|Resolved|error)' | grep -v '^ Downloaded'
  echo "wheel archives are not kept by uv; sizes above are uv's own figures for wheels >= 1 MiB"
  rm -rf "$pack" "$WORK/uv-cache-$1"
}
h "5. cold CPU sync: download lines"; sync_cold cpu cpu
if [ "${2:-}" = cu12 ]; then h "6. cold cu12 sync: download lines"; sync_cold cu12 cu126; fi

h "7. Python 3.11 download with UV_PYTHON_INSTALL_MIRROR pointing at GitHub"
UV_PYTHON_DOWNLOADS=automatic UV_PYTHON_INSTALL_MIRROR=https://github.com/astral-sh/python-build-standalone/releases/download \
  $UV venv -v --python 3.11 --managed-python --no-project "$WORK/py311" 2>&1 | grep -E 'https?://|ownload|WARN|error' | head -12
"$WORK/py311/bin/python" --version
h "7b. same without the mirror variable (uv's default order), fresh install dir"
UV_PYTHON_DOWNLOADS=automatic UV_PYTHON_INSTALL_DIR="$WORK/python-default" \
  $UV venv -v --python 3.11 --managed-python --no-project "$WORK/py311b" 2>&1 | grep -E 'https?://|ownload|WARN|error' | head -12
rm -rf "$WORK"
