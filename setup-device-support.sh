#!/bin/bash
# Manage udev rules for non-root access to additional devices
# Copyright: (c) 2022, Shane Synan <digitalcircuit36939@gmail.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

# See http://redsymbol.net/articles/unofficial-bash-strict-mode/
set -euo pipefail

# Find script folder
_LOCAL_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# udev rule paths
RULES_EXT=".rules"
LOCAL_RULES_DIR="$_LOCAL_DIR/device_rules"
SYSTEM_RULES_DIR="/etc/udev/rules.d"

if ! [ -d "$SYSTEM_RULES_DIR" ]; then
	echo "Your system doesn't have a udev rules directory at '$SYSTEM_RULES_DIR'.  Try checking your system's documentation?" >&2
	exit 1
fi

udev_reload()
{
	echo " * Reloading udev..."
	sudo udevadm control --reload-rules || return 1
	sudo udevadm trigger || return 1
}

rules_install()
{
	echo " * Copying udev device rules..."
	sudo cp --recursive "$LOCAL_RULES_DIR"/*"$RULES_EXT" "$SYSTEM_RULES_DIR"
}

rules_remove()
{
	# Only remove files with the same name as those that exist locally and with the same content
	# See https://askubuntu.com/questions/509405/undo-copy-cp-command-action/509575#509575
	echo " * Moving matching udev device rules to temporary directory..."
	PREV_DIR="$PWD" || return 1
	CLEANUP_DIR="$(mktemp -d)" || return 1
	cd "$LOCAL_RULES_DIR" || return 1
	sudo find . -maxdepth 1 -type f -exec cmp -s '{}' "$SYSTEM_RULES_DIR/{}" \; -exec mv -n "$SYSTEM_RULES_DIR/{}" "$CLEANUP_DIR"/ \; || return 1
	cd "$PREV_DIR" || return 1
	echo "Uninstalled udev rules moved to temporary directory: $CLEANUP_DIR"
	echo "Delete this directory to finish cleaning up."
}

EXPECTED_ARGS=1
if [[ $# -eq $EXPECTED_ARGS ]]; then
	case $1 in
		"install" | "i" )
			rules_install || exit 1
			udev_reload || exit 1
			;;
		"remove" | "r" )
			rules_remove || exit 1
			udev_reload || exit 1
			;;
		* )
			echo "Usage: `basename "$0"` {command: install, remove}" >&2
			exit 1
			;;
	esac
else
	echo "Usage: `basename "$0"` {command: install, remove}" >&2
	exit 1
fi
