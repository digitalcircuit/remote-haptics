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

# Rumble output
from remote_haptics.haptics_receive import ReceiverManager

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
    default_path=os.path.join("config", "logging-receiver.json"),
    default_level=logging.INFO,
    env_key="LOG_CFG",
    logging_directory=os.path.join("logs", "receiver"),
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
    for task in tasks:
        task.cancel()


async def main(config_file, write_config, listen_addr, disable_ssl, ssl_cert, ssl_key):
    """Start up the RemoteHaptics server and rumble driver."""
    # Track tasks to stop them later
    tasks = []
    loop = asyncio.get_running_loop()
    for signal_enum in [signal.SIGINT, signal.SIGTERM]:
        loop.add_signal_handler(
            signal_enum, functools.partial(immediate_exit, signal_enum, tasks)
        )

    haptics_receiver = ReceiverManager(config_file)

    if write_config:
        haptics_receiver.write_sample_config()
        print("Sample configuration file written to '{0}'".format(config_file))
        return True

    if not haptics_receiver.load_config():
        print("Problem loading configuration file '{0}'".format(config_file))
        return False

    tasks.append(
        asyncio.create_task(
            api.start_server(
                listen_addr,
                disable_ssl,
                ssl_cert,
                ssl_key,
                haptics_receiver.on_session_new_cb,
                haptics_receiver.on_session_end_cb,
                haptics_receiver.on_session_type_set_cb,
                haptics_receiver.on_haptics_updated_cb,
            )
        )
    )

    # Wait on all given tasks, ending whenever any ends
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    # Cancel other tasks
    for task in pending:
        task.cancel()


if __name__ == "__main__":
    setup_logging()
    parser = argparse.ArgumentParser(description="Haptics driver and API server.")
    default_config_path = os.path.join(
        platform_config.PATH_CONFIGURATION, "haptic-receiver.ini"
    )
    parser.add_argument(
        "-c",
        "--config-file",
        help="path to configuration file, default: {0}".format(default_config_path),
        metavar="<path>",
        default=default_config_path,
    )
    parser.add_argument(
        "-w",
        "--write-config",
        help="write out a sample configuration file then exit",
        action="store_true",
    )
    parser.add_argument(
        "-l",
        "--listen",
        help="address to listen on (default: 127.0.0.1:{0})".format(
            haptics.NET_DEFAULT_PORT
        ),
        metavar="<hostname:port>",
        default="127.0.0.1:{0}".format(haptics.NET_DEFAULT_PORT),
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
    parser.add_argument(
        "--ssl-key",
        help="SSL/TLS private key, default: {0}".format(
            platform_config.PATH_CERTS_SERVER_KEY
        ),
        metavar="<server.key>",
        default=platform_config.PATH_CERTS_SERVER_KEY,
    )
    args = parser.parse_args()

    if not ":" in args.listen:
        args.listen = "{0}:{1}".format(args.listen, haptics.NET_DEFAULT_PORT)
        print(
            "Listening port not specified, assuming default port: '{0}'".format(
                args.listen
            )
        )
    if not args.insecure and not os.path.isfile(args.ssl_cert):
        print(
            "Error: SSL/TLS certificate '{0}' cannot be read, create certificate or specify '--insecure' to disable encryption".format(
                args.ssl_cert
            )
        )
        raise SystemExit
    if not args.insecure and not os.path.isfile(args.ssl_key):
        print(
            "Error: SSL/TLS key '{0}' cannot be read, create private key or specify '--insecure' to disable encryption".format(
                args.ssl_key
            )
        )
        raise SystemExit

    asyncio.run(
        main(
            args.config_file,
            args.write_config,
            args.listen,
            args.insecure,
            args.ssl_cert,
            args.ssl_key,
        )
    )
