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
PATH_CERTS = "certs"

# Load platform-specific directories if possible
if AppDirs:
    app_dirs = AppDirs("RemoteHaptics", "digitalcircuit")
    PATH_CONFIGURATION = app_dirs.user_config_dir
    PATH_CERTS = os.path.join(app_dirs.user_data_dir, "certs")

# Determine dependent paths
PATH_CERTS_SERVER_CERT = os.path.join(PATH_CERTS, "server.cert")
PATH_CERTS_SERVER_KEY = os.path.join(PATH_CERTS, "server.key")
