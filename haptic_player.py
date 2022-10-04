"""
Copyright: (c) 2022, Shane Synan <digitalcircuit36939@gmail.com>
GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

@package RemoteHaptics
"""

import sys

if sys.version_info[0] < 3:
    raise Exception(
        "Python 3 or a more recent version is required: python3 {0} [OPTION]...".format(
            sys.argv[0]
        )
    )

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

# Platform integration
from remote_haptics import platform_config

# Controller input
from remote_haptics.haptics_send import PlayerManager

# Protocol
from remote_haptics import api

# Console user interface
from remote_haptics.console_ui import console_reset, PlayerUI

logger = logging.getLogger(__name__)

# Setup logging configuration
# This needs called before initialization to have the settings
# available when the logger is initialized.
# -------------------
# Recommended reading:
# http://victorlin.me/posts/2012/08/26/good-logging-practice-in-python
def setup_logging(
    default_path=os.path.join("config", "logging-player.json"),
    default_level=logging.INFO,
    env_key="LOG_CFG",
    logging_directory=os.path.join("logs", "player"),
):
    """Setup logging configuration"""
    # Make sure the logging directory exists
    os.makedirs(logging_directory, exist_ok=True)
    # Load configuration for logging
    path = default_path
    value = os.getenv(env_key, None)
    if value:
        path = value
    if os.path.exists(path):
        with open(path, "r") as f:
            config = json.load(f)
        logging.config.dictConfig(config)
    else:
        logging.basicConfig(level=default_level)


# See https://stackoverflow.com/questions/54383346/close-asyncio-loop-on-keyboardinterrupt-run-stop-routine
# Modified to cancel tasks instead of stopping the loop
# def immediate_exit(signame, loop: asyncio.AbstractEventLoop) -> None:
def immediate_exit(signame, tasks) -> None:
    print("\nGot signal {}, exiting".format(signame))
    stop_tasks(tasks)


def stop_tasks(tasks) -> None:
    for task in tasks:
        task.cancel()
        if task.get_name() == "player_ui":
            # When canceling the console UI, the console needs reset
            console_reset()


async def main(
    server_addr, playback_file, start_paused, disable_input, disable_ssl, ssl_cert
):
    """Start up the RemoteHaptics sender and playback."""
    tasks = []
    loop = asyncio.get_running_loop()
    for signal_enum in [signal.SIGINT, signal.SIGTERM]:
        loop.add_signal_handler(
            signal_enum, functools.partial(immediate_exit, signal_enum, tasks)
        )

    player_ui = None
    on_remark_processed_cb = None
    on_status_request_cb = None

    if not disable_input:
        player_ui = PlayerUI()
        on_remark_processed_cb = player_ui.on_remark_processed_cb
        on_status_request_cb = player_ui.on_status_request_cb

    haptics_player = PlayerManager(
        playback_file,
        on_remark_processed_cb,
        on_status_request_cb,
        functools.partial(stop_tasks, tasks),
    )

    if player_ui:
        player_ui.set_player(haptics_player)
        # Name this task for later console cleanup
        tasks.append(asyncio.create_task(player_ui.console_loop(), name="player_ui"))

    tasks.append(asyncio.create_task(haptics_player.input_queue_loop()))
    tasks.append(
        asyncio.create_task(
            api.start_client(
                server_addr,
                disable_ssl,
                ssl_cert,
                haptics_player.on_haptics_request_cb,
                api.SessionType.PLAYBACK,
            )
        )
    )

    if disable_input or not start_paused:
        # Begin playback immediately if input is disabled or not starting paused
        haptics_player.play()

    # Wait on all given tasks, ending whenever any ends
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    # Cancel other tasks
    stop_tasks(pending)


if __name__ == "__main__":
    setup_logging()
    parser = argparse.ArgumentParser(description="Haptics API playback client.")
    parser.add_argument(
        "server_addr",
        help="RemoteHaptics API server address (default port: {0})".format(
            haptics.NET_DEFAULT_PORT
        ),
        metavar="<hostname:port>",
    )
    parser.add_argument(
        "playback_file",
        help="RemoteHaptics session recording",
        metavar="<path/to/file.rec>",
    )
    parser.add_argument(
        "-p",
        "--pause",
        help="start paused, waiting for input to begin playback",
        action="store_true",
    )
    parser.add_argument(
        "-n",
        "--no-input",
        help="disable console playback UI (non-interactive)",
        action="store_true",
    )
    parser.add_argument(
        "-k", "--insecure", help="disable TLS encryption", action="store_true"
    )
    parser.add_argument(
        "--ssl-cert",
        help="SSL/TLS public certificate, default: {0}".format(
            platform_config.PATH_CERTS_SERVER_CERT
        ),
        metavar="<server.cert>",
        default=platform_config.PATH_CERTS_SERVER_CERT,
    )
    args = parser.parse_args()

    if not args.server_addr:
        parser.print_usage()
        print(
            "Error: server address must be set via <hostname:port>, e.g. '{0} 127.0.0.1:{1}'".format(
                sys.argv[0], haptics.NET_DEFAULT_PORT
            )
        )
        raise SystemExit
    if not ":" in args.server_addr:
        args.server_addr = "{0}:{1}".format(args.server_addr, haptics.NET_DEFAULT_PORT)
        print(
            "Server port not specified, assuming default port: '{0}'".format(
                args.server_addr
            )
        )
    if not args.insecure and not os.path.isfile(args.ssl_cert):
        print(
            "Error: SSL/TLS certificate '{0}' cannot be read, create certificate or specify '--insecure' to disable encryption".format(
                args.ssl_cert
            )
        )
        raise SystemExit

    if args.pause and args.no_input:
        parser.print_usage()
        print(
            "Error: '--pause' and '--no-input' can not be set at the same time (playback would never begin)."
        )
        raise SystemExit

    asyncio.run(
        main(
            args.server_addr,
            args.playback_file,
            args.pause,
            args.no_input,
            args.insecure,
            args.ssl_cert,
        )
    )
