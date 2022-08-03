"""
Copyright: (c) 2022, Shane Synan <digitalcircuit36939@gmail.com>
GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

@package RemoteHaptics
"""

import asyncio

# Logging
import logging

# Timestamps
import datetime

# Command parsing
from enum import Enum

try:
    # Console editing on Linux and macOS
    import readline
except ImportError:
    # Fall back to normal input
    pass

# Console input
import threading

# Haptics configuration
from remote_haptics import haptics

# See https://stackoverflow.com/questions/58493467/asyncio-keyboard-input-that-can-be-canceled
async def ainput(prompt: str = "") -> str:
    loop = asyncio.get_event_loop()
    input_future = loop.create_future()

    def _run():
        # line = sys.stdin.readline()
        try:
            line = input(prompt)
            loop.call_soon_threadsafe(input_future.set_result, line)
        except EOFError as eofexception:
            # Handle Ctrl+D/etc
            loop.call_soon_threadsafe(input_future.set_exception, eofexception)

    # Run thread in background (don't block exit)
    threading.Thread(target=_run, daemon=True).start()
    return await input_future


def console_reset():
    try:
        import readline
        import os

        # Workaround canceled "readline" causing console input to partially lock up
        # "-I" skips terminal initialization, preserving history/etc
        os.system("reset -I")
    except ImportError:
        # No console cleanup needed
        pass


class PlayerUI:
    class ConsoleCmd:
        PLAYPAUSE = ""
        HELP = "help"
        SEEK_FORWARD = "+"
        SEEK_BACKWARD = "-"
        GO = "go"
        POSITION = "pos"
        INFO = "info"
        HIDE = "hide"
        SHOW = "show"
        QUIT = "quit"

    class SeekType(Enum):
        EXACT = 0
        FORWARD = 1
        BACKWARD = 2

    class DeltaType(Enum):
        SECONDS = 0
        MINUTES = 1

    def __init__(self):
        """Initialize a console interface for playback control."""
        self.__logger = logging.getLogger(__name__)
        self.__haptics_player = None
        self.__hide_remarks = False

    def on_remark_processed_cb(self, remark):
        if not self.__hide_remarks:
            # 24-hour, with fractional seconds and timezone offset: "%H:%M:%S.%f%z"
            print(
                "[{0}] {1}".format(
                    remark.to_datetime().astimezone(None).strftime("%I:%M:%S %p %Z"),
                    remark.remark,
                )
            )

    def on_status_request_cb(self):
        self.__print_playback_status()

    def set_player(self, haptics_player):
        self.__haptics_player = haptics_player

    def __print_notice(self, message):
        print("> {0}".format(message))

    def __print_help(self):
        self.__print_notice("help:            show help (this)")
        self.__print_notice("<Enter>:         play/pause")
        self.__print_notice("# (e.g. 42.5):   seek to #s (e.g. 42.5s)")
        self.__print_notice("+# (e.g. +5):    skip #s ahead (e.g. 5s ahead)")
        self.__print_notice("-# (e.g. -3):    rewind #s (e.g. 3s in the past)")
        self.__print_notice("go [timestamp]:  jump to this time exactly")
        self.__print_help_timestamp_examples()
        self.__print_notice("pos:             show current playback status")
        self.__print_notice("info:            show recording information")
        self.__print_notice("hide:            hide remarks in recording")
        self.__print_notice("show:            display remarks in recording (default)")
        self.__print_notice("quit:            stop playback")

    def __print_help_timestamp_examples(self):
        # Generate timestamp examples using playback file (so copy-paste works)
        # Go 5 seconds into the future
        example_time = self.__haptics_player.recording_start + datetime.timedelta(
            seconds=5.25
        )
        # 2022-05-27 23:28
        self.__print_notice(
            " Example 1 (local):  go {0}".format(
                example_time.astimezone(None)
                .replace(tzinfo=None)
                .isoformat(sep=" ", timespec="seconds")
            )
        )
        # 2022-05-27 23:28:57.104000-04:00
        self.__print_notice(
            " Example 2 (local):  go {0}".format(
                example_time.astimezone(None).isoformat(
                    sep=" ", timespec=haptics.TIME_PRECISION_ISO
                )
            )
        )
        # 2022-05-28 03:28:57.104000+00:00
        self.__print_notice(
            " Example 3 (UTC):    go {0}".format(
                example_time.isoformat(sep=" ", timespec=haptics.TIME_PRECISION_ISO)
            )
        )

    def __print_playback_status(self):
        status = "paused:" if self.__haptics_player.paused else "playing:"
        self.__print_notice(
            "{0:<8} {1}".format(status, self.__haptics_player.position_formatted)
        )

    def __print_recording_info(self):
        self.__print_notice(
            "Time of recording (local): {0}".format(
                self.__haptics_player.recording_start.astimezone(None).strftime(
                    "%Y-%m-%d %I:%M:%S %p %Z"
                )
            )
        )

    def __set_remarks_hidden(self, hidden):
        if self.__hide_remarks == hidden:
            return

        self.__hide_remarks = hidden
        if hidden:
            self.__print_notice("Recording remarks won't be shown")
        else:
            self.__print_notice("Showing remarks in recording")

    def __toggle_playpause(self):
        self.__haptics_player.paused = not self.__haptics_player.paused
        self.__print_playback_status()

    def __go_to_timestamp(self, timestamp_str):
        if not timestamp_str:
            self.__print_notice("Missing timestamp!")
            self.__print_help_timestamp_examples()
            return

        try:
            # Parse time
            absolute_time = datetime.datetime.fromisoformat(timestamp_str)

            if not absolute_time.tzinfo:
                # Assume and convert to local timezone
                absolute_time = absolute_time.astimezone(None)

            # Negative values are handled in __seek_delta
            time_delta = (
                absolute_time - self.__haptics_player.recording_start
            ).total_seconds()
            print(time_delta)
            self.__seek_delta(self.SeekType.EXACT, time_delta)
        except ValueError:
            self.__print_notice("Invalid timestamp '{0}'!".format(timestamp_str))

    def __seek_delta(self, seek_mode, time_delta, delta_type=DeltaType.SECONDS):
        if delta_type == self.DeltaType.SECONDS:
            pass
        elif delta_type == self.DeltaType.MINUTES:
            time_delta = time_delta * 60
        else:
            raise ValueError("Invalid delta_type '{0}'!".format(delta_type))

        if seek_mode == self.SeekType.EXACT:
            self.__haptics_player.position = max(0, time_delta)
        elif seek_mode == self.SeekType.FORWARD:
            self.__haptics_player.position = max(
                0, self.__haptics_player.position + time_delta
            )
        elif seek_mode == self.SeekType.BACKWARD:
            # Don't allow seeking to negative values
            self.__haptics_player.position = max(
                0, self.__haptics_player.position + time_delta
            )
        else:
            raise ValueError("Invalid seek_mode '{0}'!".format(seek_mode))

        # Display new place
        self.__print_playback_status()

    async def console_loop(self):
        """Queue up inputs from the console interface"""
        if not self.__haptics_player:
            raise RuntimeError(
                "Haptics player object was not specified!  set_player() must be called with a valid PlayerManager before awaiting console_loop."
            )

        self.__print_notice("-" * 60)
        self.__print_recording_info()

        if self.__haptics_player.paused:
            self.__print_notice("Playback is paused (press <Enter> to play)")
        else:
            self.__print_notice("Playback is starting (press <Enter> to pause)")

        self.__print_notice("(i) Type 'help' for help")

        self.__print_notice("-" * 60)

        while True:
            try:
                input_line = await ainput()
            except EOFError:
                break

            words = input_line.split(" ")
            cmd = words[0].lower()
            words = words[1:]

            if input_line == self.ConsoleCmd.PLAYPAUSE:
                self.__toggle_playpause()
                continue
            elif cmd == self.ConsoleCmd.HELP:
                self.__print_help()
                continue
            elif cmd == self.ConsoleCmd.GO:
                self.__go_to_timestamp(" ".join(words))
                continue
            elif cmd == self.ConsoleCmd.POSITION:
                self.__print_playback_status()
                continue
            elif cmd == self.ConsoleCmd.INFO:
                self.__print_recording_info()
                continue
            elif cmd == self.ConsoleCmd.HIDE:
                self.__set_remarks_hidden(True)
                continue
            elif cmd == self.ConsoleCmd.SHOW:
                self.__set_remarks_hidden(False)
                continue
            elif cmd == self.ConsoleCmd.QUIT:
                break

            # Try to parse as time delta
            seek_mode = self.SeekType.EXACT
            if cmd.startswith(self.ConsoleCmd.SEEK_FORWARD):
                seek_mode = self.SeekType.FORWARD
            elif cmd.startswith(self.ConsoleCmd.SEEK_BACKWARD):
                seek_mode = self.SeekType.BACKWARD

            delta_type = self.DeltaType.SECONDS
            if cmd.endswith("s"):
                cmd = cmd.removesuffix("s")
                delta_type = self.DeltaType.SECONDS
            elif cmd.endswith("m"):
                cmd = cmd.removesuffix("m")
                delta_type = self.DeltaType.MINUTES

            time_delta = None
            try:
                time_delta = float(cmd)
                self.__seek_delta(seek_mode, time_delta, delta_type)
                continue
            except ValueError:
                self.__print_notice("Could not parse command!")

            # Loop again

        self.__print_notice("Exiting...")
        self.__logger.debug("Exiting player...")
