'''
Copyright: (c) 2022, Shane Synan <digitalcircuit36939@gmail.com>
GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

@package RemoteHaptics
'''

import asyncio

# Logging
import logging

# Standard error output
import sys

# Encryption
import ssl

# Timestamps and rate limiting
import datetime

# Haptics configuration
from remote_haptics import haptics

# Connection state tracking, API types
from enum import Enum

class SessionType(Enum):
    UNKNOWN = 0
    LIVE = 1
    PLAYBACK = 2

class Protocol():
    CMD_HELP = "help"
    CMD_VERSION = "ver"
    CMD_QUIT = "quit"
    CMD_SESSION_TYPE_PREFIX = "session_type:"
    CMD_TRANSMIT_HAPTICS_PREFIX = "txh:"

    REPLY_GOOD = "ACK"
    REPLY_INVALID = "INVALID_REQUEST"

    SESSION_TYPE_LIVE = "live"
    SESSION_TYPE_PLAYBACK = "playback"

    VERSION = "RemoteHaptics:0.1"

# Make errors crash the server (for development)
PROTOCOL_CRASH_ON_ERROR = True
# Send duplicate values after this much time has passed
# (Make sure to send updates slightly before the haptics would normally reset)
PROTOCOL_SEND_DUPLICATE_INTERVAL_SECS = haptics.PERSIST_DURATION_SECS * 0.95
# Maximum number of decimals to send/receive
PROTOCOL_HAPTICS_PRECISION = 6

# See https://docs.python.org/3/library/asyncio-protocol.html
# And https://gist.github.com/VSS-DEV/f03849cfa2698fd5c292d7be401a34ea
class HapticServerProtocol(asyncio.Protocol):
    def __init__(self, on_session_new_cb, on_session_end_cb, on_session_type_set_cb, on_haptics_updated_cb):
        """Initialize a haptic server.

        on_haptics_updated_cb (haptics_entries)
        haptics_entries: List of haptics items TODO better documentation
        """
        self.__logger = logging.getLogger(__name__)
        self.__on_session_new_cb = on_session_new_cb
        self.__on_session_end_cb = on_session_end_cb
        self.__on_session_type_set_cb = on_session_type_set_cb
        self.__on_haptics_updated_cb = on_haptics_updated_cb
        self.__reset_connection()

    def __reset_connection(self):
        self.__previous_cmd_txh_time = None
        self.__transport = None
        self.__peername = None

    def __send(self, message):
        if not self.__transport:
            self.__logger.debug("Transport closed, could not send message: {!r}".format(message))
            return

        if haptics.VERBOSE_API:
            self.__logger.debug("Send: {!r}".format(message))
        self.__transport.write("{}\r\n".format(message).encode())

    async def __send_delayed(self, message, delay):
        if delay > 0:
            await asyncio.sleep(delay)
        self.__send(message)

    async def __send_txh_reply_delayed(self, delay):
        await self.__send_delayed(Protocol.REPLY_GOOD, delay)
        self.__previous_cmd_txh_time = datetime.datetime.now(datetime.timezone.utc)

    def connection_made(self, transport):
        self.__reset_connection()
        self.__transport = transport
        self.__peername = transport.get_extra_info("peername")
        self.__logger.debug("Connection from {}".format(self.__peername))
        if self.__on_session_new_cb:
            self.__on_session_new_cb(self.__peername)
        if self.__on_session_type_set_cb:
            self.__on_session_type_set_cb(self.__peername, SessionType.UNKNOWN)

    def data_received(self, data):
        keep_alive = True

        message = data.decode()
        if haptics.VERBOSE_API:
            self.__logger.debug("Data received: {!r}".format(message))
        # Trim newlines/whitespace/etc
        message = message.strip()

        help_msg = "Commands: " + ", ".join((Protocol.CMD_HELP, Protocol.CMD_VERSION, Protocol.CMD_QUIT, Protocol.CMD_SESSION_TYPE_PREFIX)) + "<session type, 'live' or 'playback'>, " + Protocol.CMD_TRANSMIT_HAPTICS_PREFIX + "<0.0-1.0 haptics data>,[...]\r\nExample: " + Protocol.CMD_TRANSMIT_HAPTICS_PREFIX + "0.01,0.42"

        if message == Protocol.CMD_HELP:
            self.__send(help_msg)
        elif message == Protocol.CMD_VERSION:
            self.__send(Protocol.VERSION)
        elif message == Protocol.CMD_QUIT or message == "\x04":
            keep_alive = False
            self.__send(Protocol.REPLY_GOOD)
        elif message.startswith(Protocol.CMD_SESSION_TYPE_PREFIX):
            # Parse message
            try:
                session_type_raw = message[len(Protocol.CMD_SESSION_TYPE_PREFIX):]

                session_type = SessionType.UNKNOWN
                success = False
                if session_type_raw == Protocol.SESSION_TYPE_LIVE:
                    session_type = SessionType.LIVE
                    success = True
                    self.__logger.debug("Session type: live")
                elif session_type_raw == Protocol.SESSION_TYPE_PLAYBACK:
                    session_type = SessionType.PLAYBACK
                    success = True
                    self.__logger.debug("Session type: playback")
                else:
                    self.__logger.warning("Invalid session type: {0}".format(session_type_raw))

                if success:
                    if self.__on_session_type_set_cb:
                        self.__on_session_type_set_cb(self.__peername, session_type)
                    self.__send(Protocol.REPLY_GOOD)
                else:
                    self.__send(Protocol.REPLY_INVALID)

            except Exception as ex:
                self.__logger.warning("Failed to parse session type components from command: {0} (exception: {1})".format(message, ex))
                self.__send(Protocol.REPLY_INVALID)
                if PROTOCOL_CRASH_ON_ERROR:
                    raise
        elif message.startswith(Protocol.CMD_TRANSMIT_HAPTICS_PREFIX):
            # Parse message
            try:
                parts = message[len(Protocol.CMD_TRANSMIT_HAPTICS_PREFIX):]
                haptics_intensities = [min(1, max(0, round(float(i), PROTOCOL_HAPTICS_PRECISION))) for i in parts.split(",")]
                if haptics.VERBOSE_API:
                    self.__logger.debug("Haptics components: {!r}".format(haptics_intensities))

                if self.__on_haptics_updated_cb:
                    self.__on_haptics_updated_cb(haptics_intensities)

                # Limit event speed on the server (expected to be easier to adjust than client)
                time_delta = haptics.MAX_UPDATE_RATE_SECS
                if self.__previous_cmd_txh_time:
                    # Find how little time has elapsed
                    time_delta = (datetime.datetime.now(datetime.timezone.utc) - self.__previous_cmd_txh_time).total_seconds()

                if time_delta < haptics.MAX_UPDATE_RATE_SECS:
                    # Send after waiting the difference in delay
                    asyncio.ensure_future(self.__send_txh_reply_delayed(haptics.MAX_UPDATE_RATE_SECS - time_delta))
                else:
                    # Send immediately
                    self.__send(Protocol.REPLY_GOOD)
                    self.__previous_cmd_txh_time = datetime.datetime.now(datetime.timezone.utc)

            except Exception as ex:
                self.__logger.warning("Failed to parse haptics components from command: {0} (exception: {1})".format(message, ex))
                self.__send(Protocol.REPLY_INVALID)
                if PROTOCOL_CRASH_ON_ERROR:
                    raise
        else:
            # Invalid command
            self.__logger.info("Command: {}".format(message))
            self.__send(Protocol.REPLY_INVALID + "\r\n" + help_msg)

        if not keep_alive:
            self.__logger.debug("Closing client connection")
            if self.__on_session_end_cb:
                self.__on_session_end_cb(self.__peername)
            self.__transport.close()

    def connection_lost(self, exc):
        self.__logger.debug("Client closed the connection")
        if self.__on_session_end_cb:
            self.__on_session_end_cb(self.__peername)
        self.__reset_connection()


async def start_server(listen_addr, disable_ssl, ssl_cert, ssl_key, on_session_new_cb, on_session_end_cb, on_session_type_set_cb, on_haptics_updated_cb):
    """Start a remote haptics API server.

    TODO documentation
    """

    logger = logging.getLogger(__name__)

    # Get a reference to the event loop as we plan to use
    # low-level APIs.
    loop = asyncio.get_running_loop()

    # Find listen address
    listen_args = listen_addr.split(":")
    listen_interface = listen_args[0]
    listen_port = int(listen_args[1])

    ssl_context = None
    if not disable_ssl:
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        try:
            ssl_context.load_cert_chain(ssl_cert, ssl_key)
        except ssl.SSLError as ex:
            logger.error("Could not use SSL/TLS certificate '{2}' and key '{3}' for '{0}:{1}', details: {4}".format(listen_interface, listen_port, ssl_cert, ssl_key, ex))
            print("/!\ Could not use SSL/TLS certificate '{2}' and key '{3}' for '{0}:{1}'".format(listen_interface, listen_port, ssl_cert, ssl_key), file=sys.stderr)
            return

    try:
        server = await loop.create_server(
            lambda: HapticServerProtocol(on_session_new_cb, on_session_end_cb, on_session_type_set_cb, on_haptics_updated_cb),
            listen_interface, listen_port, ssl = ssl_context)
    except OSError as ex:
        logger.error("Failed to start server at '{0}:{1}', details: {2}".format(listen_interface, listen_port, ex))
        print("/!\ Could not start server at '{0}:{1}'".format(listen_interface, listen_port), file=sys.stderr)
        return

    if disable_ssl:
        logger.info("Unencrypted server running at '{0}:{1}'".format(listen_interface, listen_port))
    else:
        logger.info("Encrypted server running at '{0}:{1}' using cert '{2}', key '{3}'".format(listen_interface, listen_port, ssl_cert, ssl_key))

    async with server:
        await server.serve_forever()


class HapticClientProtocol(asyncio.Protocol):
    class ConnectionState(Enum):
        ERROR = 0
        CONNECTING = 1
        VERSION_CHECK = 2
        SESSION_TYPE_SET = 3
        ACTIVE = 4
        DISCONNECTED = 5

    def __init__(self, on_con_lost, on_haptics_request_cb, session_type):
        """Initialize a haptic client.

        on_con_lost: Future for when connection is lost
        on_haptics_request_cb: Callback returning list of haptics items
        TODO better documentation
        """
        self.__logger = logging.getLogger(__name__)
        self.__on_con_lost = on_con_lost
        self.__on_haptics_request_cb = on_haptics_request_cb
        self.__session_type = session_type
        self.__transport = None
        self.__peername = None
        self.__connection_state = self.ConnectionState.CONNECTING
        self.__last_haptics_intensities = []
        time_earliest = datetime.datetime(datetime.MINYEAR, 1, 1, tzinfo=datetime.timezone.utc)
        self.__last_haptics_intensities_duped = time_earliest

    def __send(self, message):
        if haptics.VERBOSE_API:
            self.__logger.debug("Send: {!r}".format(message))
        self.__transport.write("{}\r\n".format(message).encode())

    async def __send_haptics_data_delayed(self):
        await asyncio.sleep(haptics.MAX_UPDATE_RATE_SECS)
        self.__send_haptics_data()

    def __send_haptics_data(self):
        # Get haptics data
        haptics_intensities = self.__on_haptics_request_cb()
        if haptics_intensities and len(haptics_intensities):
            capped_intensities = [min(1, max(0, round(intensity, PROTOCOL_HAPTICS_PRECISION))) for intensity in haptics_intensities]

            time_now = datetime.datetime.now(datetime.timezone.utc)
            if capped_intensities != self.__last_haptics_intensities or (time_now - self.__last_haptics_intensities_duped).total_seconds() > PROTOCOL_SEND_DUPLICATE_INTERVAL_SECS:
                # Not duplicate or time elapsed, send
                reply = Protocol.CMD_TRANSMIT_HAPTICS_PREFIX + ",".join(map(str, capped_intensities))
                self.__send(reply)
                self.__last_haptics_intensities_duped = time_now
                self.__last_haptics_intensities = capped_intensities[:]
            else:
                # Re-check for changes after a delay
                asyncio.ensure_future(self.__send_haptics_data_delayed())
        else:
            # Re-check for changes after a delay
            asyncio.ensure_future(self.__send_haptics_data_delayed())
            if haptics.VERBOSE_API:
                self.__logger.debug("Missing haptics intensities, can't send command")

    def __disconnect_with_error(self, error_msg):
        self.__logger.error(error_msg)
        self.__connection_state = self.ConnectionState.ERROR
        self.__send(Protocol.CMD_QUIT)
        self.__transport.close()

    def connection_made(self, transport):
        self.__transport = transport
        self.__peername = transport.get_extra_info("peername")
        self.__logger.debug("Connected to {}".format(self.__peername))
        # Request version information, starting state machine
        self.__connection_state = self.ConnectionState.VERSION_CHECK
        self.__send(Protocol.CMD_VERSION)

    def data_received(self, data):
        message = data.decode()
        if haptics.VERBOSE_API:
            self.__logger.debug("Data received: {!r}".format(message))
        # Trim newlines/whitespace/etc
        message = message.strip()

        if self.__connection_state == self.ConnectionState.VERSION_CHECK:
            if message == Protocol.VERSION:
                # Set session type
                self.__connection_state = self.ConnectionState.SESSION_TYPE_SET
                session_type_cmd = Protocol.CMD_SESSION_TYPE_PREFIX
                if self.__session_type == SessionType.LIVE:
                    self.__send(Protocol.CMD_SESSION_TYPE_PREFIX + Protocol.SESSION_TYPE_LIVE)
                elif self.__session_type == SessionType.PLAYBACK:
                    self.__send(Protocol.CMD_SESSION_TYPE_PREFIX + Protocol.SESSION_TYPE_PLAYBACK)
                else:
                    self.__disconnect_with_error("Unknown session type '{0}', check class construction?  Disconnecting".format(self.__session_type))
            else:
                self.__disconnect_with_error("Unexpected response received, disconnecting: {!r}".format(message))
        elif self.__connection_state == self.ConnectionState.SESSION_TYPE_SET:
            if message == Protocol.REPLY_GOOD:
                # Start the normal loop
                self.__connection_state = self.ConnectionState.ACTIVE
                self.__send_haptics_data()
            else:
                self.__disconnect_with_error("Unexpected response received, disconnecting: {!r}".format(message))
        elif self.__connection_state == self.ConnectionState.ACTIVE:
            if message == Protocol.REPLY_GOOD:
                # Continue sending as fast as possible
                self.__send_haptics_data()
            else:
                self.__disconnect_with_error("Unexpected response received, disconnecting: {!r}".format(message))
        else:
            self.__disconnect_with_error("Response received during an unexpected connection state {}, disconnecting: {!r}".format(self.__connection_state, message))

    def connection_lost(self, exc):
        self.__logger.info("Server closed the connection")
        self.__connection_state = self.ConnectionState.DISCONNECTED
        try:
            self.__on_con_lost.set_result(True)
        except asyncio.exceptions.InvalidStateError:
            # Ignore error, shutting down anyways
            pass

async def start_client(server_addr, disable_ssl, ssl_cert, on_haptics_request_cb, session_type):
    """Start a remote haptics API client.

    TODO documentation
    """

    logger = logging.getLogger(__name__)

    # Get a reference to the event loop as we plan to use
    # low-level APIs.
    loop = asyncio.get_running_loop()

    # Find listen address
    server_args = server_addr.split(":")
    server_host = server_args[0]
    server_port = int(server_args[1])

    ssl_context = None
    if not disable_ssl:
        ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile = ssl_cert)

    on_con_lost = loop.create_future()
    try:
        transport, protocol = await loop.create_connection(
            lambda: HapticClientProtocol(on_con_lost, on_haptics_request_cb, session_type),
            server_host, server_port, ssl = ssl_context)
    except ConnectionRefusedError as ex:
        logger.error("Failed to connect to '{0}:{1}', details: {2}".format(server_host, server_port, ex))
        print("/!\ Could not connect to '{0}:{1}'".format(server_host, server_port), file=sys.stderr)
        return
    except ssl.SSLCertVerificationError as ex:
        logger.error("Could not verify SSL/TLS certificate '{2}' for '{0}:{1}', details: {3}".format(server_host, server_port, ssl_cert, ex))
        print("/!\ Could not verify SSL/TLS certificate '{2}' for '{0}:{1}'".format(server_host, server_port, ssl_cert), file=sys.stderr)
        return

    if disable_ssl:
        logger.info("Unencrypted connection to '{0}:{1}'".format(server_host, server_port))
    else:
        logger.info("Encrypted connection to '{0}:{1}' using cert '{2}'".format(server_host, server_port, ssl_cert))

    # Wait until the protocol signals that the connection
    # is lost and close the transport.
    try:
        await on_con_lost
    finally:
        transport.close()
