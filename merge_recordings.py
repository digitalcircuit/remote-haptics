'''
Copyright: (c) 2022, Shane Synan <digitalcircuit36939@gmail.com>
GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

@package RemoteHaptics
'''

import sys
if sys.version_info[0] < 3:
    raise Exception("Python 3 or a more recent version is required: python3 {0} [OPTION]...".format(sys.argv[0]))

# System
import os
import time

# Command line options
import argparse

# Logging
import logging
# (Skip configuration)

# Recording
from remote_haptics.recording import merge_recordings

logger = logging.getLogger(__name__)

# Setup logging configuration
# This needs called before initialization to have the settings
# available when the logger is initialized.
# -------------------
# Recommended reading:
# http://victorlin.me/posts/2012/08/26/good-logging-practice-in-python
def setup_logging(
    default_path='config-logging.json',
    default_level=logging.INFO,
    env_key='LOG_CFG',
    logging_directory='logs'
):
    """Setup logging configuration

    """
    # Make sure the logging directory exists
    if not os.path.exists(logging_directory):
        os.makedirs(logging_directory)
    # Load configuration for logging
    path = default_path
    value = os.getenv(env_key, None)
    if value:
        path = value
    if os.path.exists(path):
        with open(path, 'r') as f:
            config = json.load(f)
        logging.config.dictConfig(config)
    else:
        logging.basicConfig(level=default_level)

def main(output_file, recording_filenames, include_backups):
    if not include_backups:
        # Gather all backup files
        backup_files = [file for file in recording_filenames if file.endswith("~")]
        if backup_files:
            print("Excluding backup files (use '--include-backups' to override): '{0}'".format("', '".join(backup_files)))
            # Exclude all files ending in "~"
            recording_filenames = [file for file in recording_filenames if not file.endswith("~")]

    # Process recordings
    merge_recordings(output_file, recording_filenames)

if __name__ == "__main__":
    setup_logging()
    parser = argparse.ArgumentParser(description = "Haptics recording merger.")
    parser.add_argument("output_file", help="Output of merged RemoteHaptics session recording", metavar="<merged.rec>")
    parser.add_argument("recording_files", help="RemoteHaptics session recording to merge", nargs='+', metavar="<recording.rec>")
    parser.add_argument("-f", "--force", help="Overwrite the output file when it exists", action="store_true")
    parser.add_argument("-i", "--include-backups", help="Don't exclude backup files (files ending in '~')", action="store_true")
    args = parser.parse_args()

    if os.path.isfile(args.output_file) and not args.force:
        print("Error: Output file '{0}' already exists.  Specify '--force' to overwrite.".format(args.output_file))
        raise SystemExit

    main(args.output_file, args.recording_files, args.include_backups)
    print("Recordings merged!")
