#!/usr/bin/env bash
# Set up T-Blade3 in a conda environment and install the `tblade` command.
#
#   ./install.sh              create or update the "tblade" env, build, install, link `tblade`
#   ./install.sh --no-link    the same, but do not put `tblade` in ~/.local/bin
#
# Afterwards `tblade` starts the GUI (`tblade <case folder>` opens a case) and `tb3` is the command-line
# tool. With the link, `tblade` works from any shell without activating the env; without it,
# run `conda activate tblade` first.
set -euo pipefail

ENV_NAME=tblade
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LINK=1
for arg in "$@"; do
    case "$arg" in
        --no-link) LINK=0 ;;
        -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

# Find conda (prefer mamba for speed)
CONDA=""
for c in mamba conda; do
    if command -v "$c" >/dev/null 2>&1; then CONDA="$(command -v "$c")"; break; fi
done
if [ -z "$CONDA" ] && [ -n "${CONDA_EXE:-}" ]; then CONDA="$CONDA_EXE"; fi
if [ -z "$CONDA" ]; then
    for base in "$HOME/miniforge3" "$HOME/.miniforge" "$HOME/mambaforge" "$HOME/miniconda3" "$HOME/anaconda3"; do
        for c in mamba conda; do
            if [ -x "$base/bin/$c" ]; then CONDA="$base/bin/$c"; break 2; fi
        done
    done
fi
if [ -z "$CONDA" ]; then
    echo "conda not found. Install Miniforge (https://conda-forge.org/download/) and rerun." >&2
    exit 1
fi
echo "== using $CONDA"

# Create or update the environment
if "$CONDA" env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
    echo "== updating env $ENV_NAME"
    "$CONDA" env update -y -n "$ENV_NAME" -f "$REPO/python/environment.yml" --prune
else
    echo "== creating env $ENV_NAME"
    "$CONDA" env create -y -f "$REPO/python/environment.yml"
fi
run() { "$CONDA" run -n "$ENV_NAME" --cwd "$REPO" "$@"; }
PREFIX="$(run python -c 'import sys; print(sys.prefix)')"

# Build T-Blade3 with the env's gfortran. Old objects are removed so nothing built against
# another env (whose library path is baked into the binaries) is left behind.
echo "== building T-Blade3"
rm -f "$REPO"/source/*.o "$REPO"/source/*.mod
rm -rf "$REPO/bin" "$REPO/lib"
run make code library

# Install the Python package (editable, so it finds bin/ and lib/ in this checkout)
echo "== installing the tblade3 Python package"
run python -m pip install --no-deps --no-build-isolation -e "$REPO/python"

# Check that Python finds the executable and the library
run python -c "from tblade3 import paths; print('executable', paths.executable()); print('library   ', paths.library())"

if [ "$LINK" = 1 ]; then
    mkdir -p "$HOME/.local/bin"
    ln -sf "$PREFIX/bin/tblade" "$HOME/.local/bin/tblade"
    echo "== linked $HOME/.local/bin/tblade -> $PREFIX/bin/tblade"
    case ":$PATH:" in
        *":$HOME/.local/bin:"*) ;;
        *) echo "   note: ~/.local/bin is not on PATH; add it in ~/.bashrc:  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
    esac
fi

echo
echo "Done. Start the GUI with:  tblade            (or: tblade <case folder>)"
