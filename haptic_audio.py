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
# Control-C handling
import signal
import functools

# Logging
import logging
# Logging configuration
import json
import logging.config

# Make things asynchronous
import asyncio

# Configuration
from remote_haptics import haptics

# Controller input
from remote_haptics.haptics_audio import AudioManager

# Protocol
from remote_haptics import api

logger = logging.getLogger(__name__)

# Setup logging configuration
# This needs called before initialization to have the settings
# available when the logger is initialized.
# -------------------
# Recommended reading:
# http://victorlin.me/posts/2012/08/26/good-logging-practice-in-python
def setup_logging(
    default_path=os.path.join('config', 'logging-audio.json'),
    default_level=logging.INFO,
    env_key='LOG_CFG',
    logging_directory=os.path.join('logs', 'audio')
):
    """Setup logging configuration

    """
    # Make sure the logging directory exists
    os.makedirs(logging_directory, exist_ok=True)
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

# See https://stackoverflow.com/questions/54383346/close-asyncio-loop-on-keyboardinterrupt-run-stop-routine
# Modified to cancel tasks instead of stopping the loop
# def immediate_exit(signame, loop: asyncio.AbstractEventLoop) -> None:
def immediate_exit(signame, tasks) -> None:
    print("\nGot signal {}, exiting".format(signame))
    for task in tasks:
        task.cancel()

async def main(server_addr, audio_mode, disable_ssl, ssl_cert):
    """Start up the RemoteHaptics sender and audio.
    """
    tasks = []
    loop = asyncio.get_running_loop()
    for signal_enum in [signal.SIGINT, signal.SIGTERM]:
        loop.add_signal_handler(signal_enum, functools.partial(immediate_exit, signal_enum, tasks))

    haptics_audio = AudioManager(audio_mode)

    tasks.append(asyncio.create_task(haptics_audio.input_queue_loop()))
    tasks.append(asyncio.create_task(api.start_client(server_addr, disable_ssl, ssl_cert, haptics_audio.on_haptics_request_cb, api.SessionType.PLAYBACK)))

    # Wait on all given tasks, ending whenever any ends
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    # Cancel other tasks
    for task in pending:
        task.cancel()

if __name__ == "__main__":
    setup_logging()
    parser = argparse.ArgumentParser(description = "Haptics API audio client.")
    parser.add_argument("server_addr", help="RemoteHaptics API server address (default port: {0})".format(haptics.NET_DEFAULT_PORT), metavar="<hostname:port>")
    parser.add_argument("-m", "--audio-mode", help="Audio mode - 'all', 'bass', 'mid' or 'treble' (default: bass)", metavar="<mode>", default = "bass")
    parser.add_argument("-k", "--insecure", help="disable TLS encryption", action="store_true")
    parser.add_argument("--ssl-cert", help="SSL/TLS public certificate", metavar="<server.cert>", default = os.path.join("certs", "server.cert"))
    args = parser.parse_args()

    if not args.server_addr:
        parser.print_usage()
        print("Error: server address must be set via <hostname:port>, e.g. '{0} 127.0.0.1:{1}'".format(sys.argv[0], haptics.NET_DEFAULT_PORT))
        raise SystemExit
    if not ":" in args.server_addr:
        args.server_addr = "{0}:{1}".format(args.server_addr, haptics.NET_DEFAULT_PORT)
        print("Server port not specified, assuming default port: '{0}'".format(args.server_addr))

    asyncio.run(main(args.server_addr, args.audio_mode, args.insecure, args.ssl_cert))
