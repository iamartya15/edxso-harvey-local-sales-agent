#!/bin/bash
# restore_ollama.sh — reinstall the Ollama binary after a VM restart.
#
# The VM restarts roughly every ~2h and wipes /usr/local (binary, zstd,
# apt lists). The models in ~/.ollama/models/ and this repo (both under ~)
# survive, so recovery is binary-only — no model re-download.
#
# Usage:  bash scripts/restore_ollama.sh [--no-serve]
#   --no-serve: install the binary only, do not start the server.
#
# What it does:
#   1. If /usr/local/bin/ollama exists, skips the install.
#   2. Otherwise downloads ollama-linux-amd64.tar.zst (~1.5 GB) to ~/ (NOT
#      /tmp — /tmp is a 512 MiB tmpfs) and extracts it to /usr/local with
#      Python zstandard (pip install zstandard first if missing; avoids
#      apt, whose update is slow/stuck after restarts).
#   3. Starts `ollama serve` in the background (unless --no-serve) and
#      verifies `ollama list` shows the models.
# Exit 0 when the server answers on localhost:11434 (or the binary is
# installed with --no-serve), non-zero otherwise.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARBALL="$HOME/ollama-linux-amd64.tar.zst"
URL="https://ollama.com/download/ollama-linux-amd64.tar.zst"
NO_SERVE=0
[ "${1:-}" = "--no-serve" ] && NO_SERVE=1

if [ -x /usr/local/bin/ollama ]; then
    echo "ollama binary already present: $(/usr/local/bin/ollama --version 2>/dev/null | tail -1)"
else
    echo "ollama binary missing — reinstalling (models in ~/.ollama survive, no re-download needed)..."
    if ! "$ROOT/.venv/bin/python" -c "import zstandard" 2>/dev/null; then
        echo "installing zstandard into the project venv..."
        "$ROOT/.venv/bin/pip" install -q zstandard || {
            echo "pip install zstandard failed; trying system python3"; python3 -m pip install --user -q zstandard; }
    fi
    echo "downloading $URL (~1.5 GB, ~6 min)..."
    if [ -f "$TARBALL" ] && [ "$(stat -c %s "$TARBALL" 2>/dev/null)" = "1545767640" ]; then
        echo "tarball already present with expected size — skipping download"
    else
        curl -fsSL "$URL" -o "$TARBALL" || { echo "download failed"; exit 1; }
    fi
    echo "extracting to /usr/local ..."
    "$ROOT/.venv/bin/python" - "$TARBALL" <<'EOF'
import sys, tarfile, zstandard
with open(sys.argv[1], 'rb') as fh:
    with zstandard.ZstdDecompressor().stream_reader(fh) as reader:
        with tarfile.open(fileobj=reader, mode='r|') as tf:
            tf.extractall('/usr/local')
print('extracted')
EOF
    rm -f "$TARBALL"
    echo "installed: $(/usr/local/bin/ollama --version 2>/dev/null | tail -1)"
fi

if [ "$NO_SERVE" = 1 ]; then
    exit 0
fi
if curl -fs -m 3 http://localhost:11434/api/version >/dev/null 2>&1; then
    echo "ollama serve already running"
else
    echo "starting ollama serve ..."
    nohup /usr/local/bin/ollama serve >/dev/null 2>&1 &
    for _ in $(seq 1 10); do
        sleep 2
        curl -fs -m 3 http://localhost:11434/api/version >/dev/null 2>&1 && break
    done
fi
echo "--- ollama list ---"
/usr/local/bin/ollama list
curl -fs -m 5 http://localhost:11434/api/version && echo && echo "Ollama restored OK"
