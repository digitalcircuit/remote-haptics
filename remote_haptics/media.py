"""
Copyright: (c) 2022, Shane Synan <digitalcircuit36939@gmail.com>
GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

@package RemoteHaptics
"""

import asyncio

# Logging
import logging

# System, managing relative file paths
import os

# Haptics setup
from remote_haptics import haptics

# Event management
import datetime

# Try to import MPV if possible
MPV = None
try:
    from python_mpv_jsonipc import MPV
except ImportError:
    pass


class MediaPlayer:
    LIKELY_SOCKET_ERRORS = (
        BrokenPipeError,
        ConnectionResetError,
        OSError,
        TimeoutError,
    )

    def __init__(
        self,
        media_base_dir,
        external_paused_set_cb,
        external_position_set_cb,
        external_quit_cb,
    ):
        self.__logger = logging.getLogger(__name__)

        if not haptics.VERBOSE_MEDIA:
            # Remove MPV logging
            logging.getLogger("mpv-jsonipc").setLevel(logging.FATAL)

        time_earliest = datetime.datetime(
            datetime.MINYEAR, 1, 1, tzinfo=datetime.timezone.utc
        )
        self.__async_main_loop = asyncio.get_event_loop()
        self.__logging_id = "<no-media-loaded>"
        self.__base_dir = media_base_dir
        self.__player_external_paused_cb = external_paused_set_cb
        self.__player_external_position_set_cb = external_position_set_cb
        self.__player_external_quit_cb = external_quit_cb
        self.__player_module_found = MPV is not None
        self.__player = None
        self.__ignore_event_until = time_earliest
        self.__full_offset = 0
        self.__media_negative_offset_warn_hash = []
        self.__media_file = None
        self.__media_ended = False
        self.__ensure_player()

    @property
    def paused(self):
        if not self.__player:
            return None

        try:
            return self.__player.pause
        except self.LIKELY_SOCKET_ERRORS as ex:
            # Handle unexpected disconnects
            if not self.__media_file:
                # No media loaded yet, ignore
                return None
            if haptics.VERBOSE_MEDIA:
                self.__logger.debug(
                    "[{0}] Error when fetching paused state: {1}".format(
                        self.__logging_id, ex
                    )
                )
            else:
                self.__logger.debug(
                    "[{0}] Error when fetching paused state: {1}".format(
                        self.__logging_id, type(ex).__name__
                    )
                )
            return None

    @paused.setter
    def paused(self, value):
        if not self.__player:
            return
        cur_paused = self.paused
        if cur_paused is None:
            return
        if cur_paused == value:
            return

        if haptics.VERBOSE_MEDIA:
            self.__logger.debug(
                "[{0}] Setting paused = {1}".format(self.__logging_id, value)
            )

        self.__ignore_nearby_events()
        self.__player.pause = value

    @property
    def position(self):
        if not self.__player:
            return None

        try:
            return self.__player.time_pos
        except self.LIKELY_SOCKET_ERRORS as ex:
            # Handle unexpected disconnects
            if not self.__media_file:
                # No media loaded yet, ignore
                return None
            if haptics.VERBOSE_MEDIA:
                self.__logger.debug(
                    "[{0}] Error when fetching position: {1}".format(
                        self.__logging_id, ex
                    )
                )
            else:
                self.__logger.debug(
                    "[{0}] Error when fetching position: {1}".format(
                        self.__logging_id, type(ex).__name__
                    )
                )
            return None

    @position.setter
    def position(self, value):
        cur_position = self.position
        if cur_position is None:
            # Can't control position if no player or not readable
            return
        if cur_position == value:
            return

        # If the value exceeds duration, the media player automatically stops

        # Allow a slight variance from the exact time
        if value > (cur_position - haptics.MEDIA_POSITION_SKEW_SECS) and value < (
            cur_position + haptics.MEDIA_POSITION_SKEW_SECS
        ):
            # if haptics.VERBOSE_MEDIA:
            #    self.__logger.debug("[{0}] Ignoring seek to {1:f}s, already at {2:f}s".format(self.__logging_id, round(value, haptics.TIME_PRECISION_PLACES), round(cur_position, haptics.TIME_PRECISION_PLACES)))
            return

        if haptics.VERBOSE_MEDIA:
            deviation = round(value - cur_position, haptics.TIME_PRECISION_PLACES)
            self.__logger.debug(
                "[{0}] Delta of {1:f}s, seeking to {2:f}s from {3:f}s".format(
                    self.__logging_id,
                    deviation,
                    round(value, haptics.TIME_PRECISION_PLACES),
                    round(cur_position, haptics.TIME_PRECISION_PLACES),
                )
            )

        if self.__media_ended:
            if haptics.VERBOSE_MEDIA:
                self.__logger.debug(
                    "[{0}] Media already ended, restarting player to seek to {1:f}s".format(
                        self.__logging_id, round(value, haptics.TIME_PRECISION_PLACES)
                    )
                )
            self.__start_player()
        self.__ignore_nearby_events()
        self.__player.time_pos = value

    @property
    def position_with_offset(self):
        if self.position is None:
            return None

        return self.position - self.__full_offset

    def sync(self, paused, position_without_offset):
        if not self.__player_module_found:
            return

        if not self.__player:
            self.__start_player()

        new_position = position_without_offset + self.__full_offset

        if new_position < 0:
            # Pause for negative values
            self.position = 0
            self.paused = True
            return

        self.paused = paused
        self.position = new_position

    def play_with_offset(self, time_delta, offset, media_file):
        # Set logging identifier
        self.__logging_id = os.path.basename(media_file)

        # Load and play media
        self.__full_offset = offset + time_delta
        self.__media_file = media_file

        if (
            time_delta + offset < 0
            and self.__get_media_hash() not in self.__media_negative_offset_warn_hash
        ):
            self.__logger.debug(
                "[{0}] Media start time set for the future (loaded early?), will pause for {1}s to catch up".format(
                    self.__logging_id, -(time_delta + offset)
                )
            )
            if self.__get_media_hash() not in self.__media_negative_offset_warn_hash:
                self.__media_negative_offset_warn_hash.append(self.__get_media_hash())

        success = self.__start_player()

        if success:
            if haptics.VERBOSE_MEDIA:
                self.__logger.debug(
                    "[{0}] Playing media '{1}' with offset {2}s (at time delta {3}s)".format(
                        self.__logging_id,
                        os.path.basename(media_file),
                        offset,
                        time_delta,
                    )
                )

    def quit(self, force_shutdown):
        if self.__player:
            self.__ignore_nearby_events()
            if force_shutdown:
                if haptics.VERBOSE_MEDIA:
                    self.__logger.debug(
                        "[{0}] Forcibly shutting down media player".format(
                            self.__logging_id
                        )
                    )
                self.__player.terminate()
            else:
                if haptics.VERBOSE_MEDIA:
                    self.__logger.debug(
                        "[{0}] Normally shutting down media player".format(
                            self.__logging_id
                        )
                    )
                self.__player.quit()

    def __ignore_nearby_events(self):
        self.__ignore_event_until = datetime.datetime.now(
            datetime.timezone.utc
        ) + datetime.timedelta(seconds=0.1)

    @property
    def __ignore_events(self):
        return datetime.datetime.now(datetime.timezone.utc) < self.__ignore_event_until

    def __get_media_hash(self):
        return hash(self.__media_file) + hash(self.__full_offset)

    def __ensure_player(self):
        if self.__player:
            return

        if not self.__player_module_found:
            # MPV support not available
            return

        # Change to recording directory to ensure relative paths work
        prev_dir = os.curdir
        os.chdir(self.__base_dir)

        # Create media player if available
        # Disable album art display
        self.__player = MPV(quit_callback=self.__media_quit_cb, audio_display="no")
        # To disable custom input: input_default_bindings=False, osc=False
        # Attach handlers
        self.__ignore_nearby_events()
        self.__player.bind_event(
            "start-file", self.__media_event_ignore_other_events_cb
        )
        self.__player.bind_event(
            "file-loaded", self.__media_event_ignore_other_events_cb
        )
        self.__player.bind_property_observer("eof-reached", self.__media_eof_cb)
        self.__player.bind_property_observer("pause", self.__media_toggle_pause_cb)
        self.__player.bind_property_observer("seeking", self.__media_seek_cb)

        # Restore working directory
        os.chdir(prev_dir)

    def __start_player(self):
        self.__ensure_player()
        if not self.__player:
            self.__logger.warning(
                "[{0}] Can't play media '{1}', unable to start Python MPV over IPC".format(
                    self.__logging_id, os.path.basename(self.__media_file)
                )
            )
            return False

        self.__ignore_nearby_events()
        self.__media_ended = False
        self.__player.play(self.__media_file)

    def __media_event_ignore_other_events_cb(self, event_data):
        self.__ignore_nearby_events()

    def __media_quit_cb(self):
        self.__media_ended = True

        if self.__ignore_events:
            return

        if haptics.VERBOSE_MEDIA:
            self.__logger.debug("[{0}] Media player quit".format(self.__logging_id))
        if self.__player_external_quit_cb:
            self.__async_main_loop.call_soon_threadsafe(self.__player_external_quit_cb)
        self.__player = None

    def __media_eof_cb(self, name, value):
        if value:
            self.__ignore_nearby_events()
            self.__media_ended = True

    def __media_toggle_pause_cb(self, name, value):
        if self.__ignore_events:
            # print("[{0}] IGNORING media toggle pause: {1}".format(self.__logging_id, value))
            return

        # Ignore when playback ended
        if self.__media_ended:
            return

        if haptics.VERBOSE_MEDIA:
            print("[{0}] Media toggle pause: {1}".format(self.__logging_id, value))

        # Toggle play/pause
        if self.__player_external_paused_cb:
            self.__async_main_loop.call_soon_threadsafe(
                self.__player_external_paused_cb, value
            )

    def __media_seek_cb(self, name, value):
        if value:
            # Ignore seeking = True
            return

        # Ignore when playback ended
        if self.__media_ended:
            return

        # Ignore when no position is available
        if self.position is None:
            return

        if self.__ignore_events:
            # print("[{0}] IGNORING media seek".format(self.__logging_id))
            return

        if haptics.VERBOSE_MEDIA:
            print(
                "[{0}] Media seek: {1} (with offset: {2})".format(
                    self.__logging_id, self.position, self.position_with_offset
                )
            )

        # Set seek position
        if self.__player_external_position_set_cb:
            # Media player runs on a different thread
            self.__async_main_loop.call_soon_threadsafe(
                self.__player_external_position_set_cb, self.position_with_offset
            )
