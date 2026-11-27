#!/usr/bin/env bash
# Launch the T-Blade3 GUI (conda env tblade). Extra arguments are passed to the app.
source "$HOME/.miniforge/etc/profile.d/conda.sh"
conda activate tblade
[ -z "${DISPLAY:-}" ] && export DISPLAY=:1
LOG="$HOME/Projects/FEA/T-Blade3/build/launch_tblade3_gui.log"
mkdir -p "$(dirname "$LOG")"
cd "$HOME/Projects/FEA"
exec tb3-gui "$@" >>"$LOG" 2>&1
