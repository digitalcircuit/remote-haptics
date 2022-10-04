"""
Copyright: (c) 2022, Shane Synan <digitalcircuit36939@gmail.com>
GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

@package RemoteHaptics
"""

import os

# Try to import AppDirs if possible
AppDirs = None
try:
    from appdirs import AppDirs
except ImportError:
    pass

# Specify default directories
PATH_CONFIGURATION = "config"

# Load platform-specific directories if possible
if AppDirs:
    app_dirs = AppDirs("RemoteHaptics", "digitalcircuit")
    PATH_CONFIGURATION = app_dirs.user_config_dir
