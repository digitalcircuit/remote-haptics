#!/bin/bash
# Setup and activate Python virtual environment for RemoteHaptics
# Copyright: (c) 2022, Shane Synan <digitalcircuit36939@gmail.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

# NOTE: source this file in, don't run in subshell

# Find script folder
_LOCAL_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# 1.  The "proper" way
export VENV="$_LOCAL_DIR/.env"
# Allow system packages since evdev doesn't build properly
python3 -m venv --system-site-packages "$VENV"
# Update
"$VENV/bin/pip" install --upgrade --requirement requirements-media.txt --requirement requirements-dev.txt
# Activate
source "$VENV/bin/activate"

# 2.  The easy way
#
# No pip/etc required (single file, no dependencies)
# wget https://raw.githubusercontent.com/iwalton3/python-mpv-jsonipc/master/python_mpv_jsonipc.py
#
# Development requirements should probably be installed via venv.
