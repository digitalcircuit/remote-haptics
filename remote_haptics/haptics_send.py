'''
Copyright: (c) 2022, Shane Synan <digitalcircuit36939@gmail.com>
GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

@package RemoteHaptics
'''

import asyncio

# System
import os

# Logging
import logging

# Timestamps and physics
import datetime

# Haptics setup
from remote_haptics import haptics

# Controller input
from remote_haptics import evdev_driver
import evdev

# Playback
from remote_haptics import recording

# Media playback
from remote_haptics.media import MediaPlayer

# Configuration file
import configparser

# Feedback classes
from abc import ABC, abstractmethod
# Class ordering
import functools
# Custom button/trigger categories
from enum import Enum

@functools.total_ordering
class FeedbackMapperAbstract(ABC):
    def __init__(self, haptics_source, order):
        """Initialize a feedback mapping between inputs and outputs.

        haptics_source: Absolute input devices to receive events from
        """
        self.__logger = logging.getLogger(__name__)
        self.__source = haptics_source
        self.__order = order

    # See https://stackoverflow.com/questions/8796886/is-it-safe-to-just-implement-lt-for-a-class-that-will-be-sorted
    def __eq__(self, other):
        return (self.order == other.order)

    def __lt__(self, other):
        return (self.order < other.order)

    @property
    def _source(self):
        """Get the input device (meant for subclasses)
        """
        return self.__source

    @property
    def order(self):
        """Get the feedback mapper order
        """
        return self.__order

    @abstractmethod
    async def input_queue_loop(self):
        """Queue inputs from this device for next retrieval.
        """
        return False

    @abstractmethod
    def retrieve_inputs(self):
        """Take the queued input values from this input device.

        Returns list of 0-1 decimal values representing haptics intensities
        """
        return False


class FeedbackMapperPlayback(FeedbackMapperAbstract):
    def __init__(self, recording_path, on_remark_processed_cb, on_media_processed_cb):
        """Initialize a feedback mapping between recording file and outputs.

        recording_path: Path to recording to play back
        on_remarks_processed_cb: Callback for processing remarks embedded in recording
        """
        super().__init__(recording_path, 0)

        self.__logger = logging.getLogger(__name__)
        # Get a reference to the event loop as we plan to use
        # low-level APIs.
        loop = asyncio.get_running_loop()
        self.__on_playback_finished = loop.create_future()
        self.__on_remark_processed_cb = on_remark_processed_cb
        self.__on_media_processed_cb = on_media_processed_cb
        self.__haptics_player = recording.HapticsReader(recording_path, self.__on_playback_finished)
        self.__player_is_seeking = False
        self.__player_last_retrieve_inputs = datetime.datetime.now(datetime.timezone.utc)
        self.__player_last_input_count = 0
        self.__player_position_sec = 0
        self.__player_playing = False
        # Load initial values before initial fetch
        self.__restart_playback()

    def play(self):
        #self.__logger.debug("Playback requested")
        self.__player_playing = True

    def pause(self):
        #self.__logger.debug("Pause requested")
        # Mark as seeking to avoid time skip (technically seeking in place)
        self.__player_is_seeking = True
        self.__player_playing = False

    @property
    def paused(self):
        return not self.__player_playing

    @paused.setter
    def paused(self, value):
        if not value and self.paused:
            # Paused = false, currently paused, press play
            self.play()
        if value and not self.paused:
            # Paused = true, currently playing, press pause
            self.pause()

    @property
    def recording_start(self):
        return self.__haptics_player.recording_start

    @property
    def position(self):
        return self.__player_position_sec

    @position.setter
    def position(self, value):
        if value == self.position:
            return

        self.__player_is_seeking = True
        self.__player_position_sec = value

    @property
    def position_formatted(self):
        relative_time = datetime.timedelta(seconds=self.position)
        absolute_time = self.__haptics_player.delta_to_datetime(relative_time)
        # timedelta does not implement __format__ arguments
        return "{0:<13} = {1:<15} [time: {2}]".format(str(round(self.position, 6)) + "s", str(relative_time), absolute_time.isoformat(sep=" ", timespec=haptics.TIME_PRECISION_ISO))

    def __restart_playback(self):
        self.position = 0
        self.__player_playing = False

    async def input_queue_loop(self):
        """Queue inputs from this device for next retrieval.
        """
        await self.__on_playback_finished

    def retrieve_inputs(self):
        """Take the queued input values from this input device.

        Returns list of 0-1 decimal values representing haptics intensities
        """

        if not self.__player_playing:
            # Return empty results when paused, don't advance position
            return [0] * self.__player_last_input_count

        time_delta_sec = self.__player_position_sec
        if self.__player_is_seeking:
            # When seeking, don't advance time forwards
            self.__player_is_seeking = False
        else:
            # Advance by the amount of time elapsed since last call
            time_delta_sec += (datetime.datetime.now(datetime.timezone.utc) - self.__player_last_retrieve_inputs).total_seconds()

        records = self.__haptics_player.get_records_until(self.__player_position_sec)

        # Assume no results
        input_peaks = None

        for record in records:
            # Process each record
            if isinstance(record, recording.EntryInputs):
                # Haptics data
                if not input_peaks or len(record.inputs) != self.__player_last_input_count:
                    # Initialize peak value tracker
                    self.__player_last_input_count = len(record.inputs)
                    input_peaks = [0] * self.__player_last_input_count

                # Update peak values
                for i in range(0, len(record.inputs)):
                    input_peaks[i] = max(record.inputs[i], input_peaks[i])
            elif isinstance(record, recording.EntryRemark):
                # Recording remark
                self.__on_remark_processed_cb(record)
            elif isinstance(record, recording.EntryMediaAbstract):
                # Media command
                self.__on_media_processed_cb(record)
            else:
                raise Exception("Unexpected/invalid record type: {0}".format(record))

        # Update time elapsed
        self.__player_position_sec = time_delta_sec
        self.__player_last_retrieve_inputs = datetime.datetime.now(datetime.timezone.utc)

        # Return results
        return input_peaks


class FeedbackMapperAnalogTrigger(FeedbackMapperAbstract):
    DEBUG_TRIGGER_DETECT = False

    class Trigger(Enum):
        LEFT = 0
        RIGHT = 1

    def __init__(self, haptics_input, order):
        """Initialize a feedback mapping between analog trigger inputs and outputs.

        haptics_input: Absolute input devices to receive events from
        """
        super().__init__(haptics_input, order)
        self.__logger = logging.getLogger(__name__)
        # Limit to triggers
        # Xbox 360: ABS_Z, ABS_RZ
        # Stadia: ABS_BRAKE, ABS_GAS
        self.__trigger_codes = {}
        self.__trigger_value = {}
        self.__trigger_peak = {}
        self.__trigger_value[self.Trigger.LEFT] = 0
        self.__trigger_value[self.Trigger.RIGHT] = 0
        self.__trigger_codes[self.Trigger.LEFT] = [evdev.ecodes.ABS_Z, evdev.ecodes.ABS_BRAKE]
        self.__trigger_codes[self.Trigger.RIGHT] = [evdev.ecodes.ABS_RZ, evdev.ecodes.ABS_GAS]
        self.__reset_peaks()

    def __update_peaks(self):
        for trigger_type in self.Trigger:
            self.__trigger_peak[trigger_type] = max(self.__trigger_value[trigger_type], self.__trigger_peak[trigger_type])

    def __reset_peaks(self):
        for trigger_type in self.Trigger:
            self.__trigger_peak[trigger_type] = self.__trigger_value[trigger_type]

    async def input_queue_loop(self):
        """Queue inputs from this device for next retrieval.
        """
        async for event in self._source.device_events_loop():
            # Ignore non-absolute events
            if event.type != evdev.ecodes.EV_ABS:
                continue

            if self.DEBUG_TRIGGER_DETECT and event.value == evdev_driver.AbsInputDevice.TRIGGER_MAX:
                print("Device: {0}, event: {1} [{2}]".format(self._source.name, evdev.ecodes.ABS[event.code], str(event)))

            # Limit to triggers
            # Track maximum value, allowing for quick taps
            if event.code in self.__trigger_codes[self.Trigger.LEFT]:
                self.__trigger_value[self.Trigger.LEFT] = event.value
                self.__update_peaks()
            elif event.code in self.__trigger_codes[self.Trigger.RIGHT]:
                self.__trigger_value[self.Trigger.RIGHT] = event.value
                self.__update_peaks()

    def retrieve_inputs(self):
        """Take the queued input values from this input device.

        Returns list of 0-1 decimal values representing haptics intensities
        """
        result = [self.__trigger_peak[self.Trigger.LEFT] / evdev_driver.AbsInputDevice.TRIGGER_MAX, self.__trigger_peak[self.Trigger.RIGHT] / evdev_driver.AbsInputDevice.TRIGGER_MAX]
        self.__reset_peaks()
        return result


class FeedbackMapperAnalogPedal(FeedbackMapperAbstract):
    DEBUG_TRIGGER_DETECT = False

    class Pedal(Enum):
        GAS = 0
        BRAKE = 1
        CLUTCH = 2

    def __init__(self, haptics_input, order):
        """Initialize a feedback mapping between analog trigger inputs and outputs.

        haptics_input: Absolute input devices to receive events from
        """
        super().__init__(haptics_input, order)
        self.__logger = logging.getLogger(__name__)
        # Limit to certain inputs
        # FANATEC ClubSport USB Pedal: ABS_X, ABS_Y, ABS_Z
        self.__axis_codes = {}
        self.__axis_value = {}
        self.__axis_peak = {}
        self.__axis_value[self.Pedal.GAS] = 0
        self.__axis_value[self.Pedal.BRAKE] = 0
        self.__axis_value[self.Pedal.CLUTCH] = 0
        self.__axis_codes[self.Pedal.GAS] = [evdev.ecodes.ABS_X, evdev.ecodes.ABS_GAS]
        self.__axis_codes[self.Pedal.BRAKE] = [evdev.ecodes.ABS_Y, evdev.ecodes.ABS_BRAKE]
        self.__axis_codes[self.Pedal.CLUTCH] = [evdev.ecodes.ABS_Z]
        self.__reset_peaks()

    def __update_peaks(self):
        for trigger_type in self.Pedal:
            self.__axis_peak[trigger_type] = max(self.__axis_value[trigger_type], self.__axis_peak[trigger_type])

    def __reset_peaks(self):
        for trigger_type in self.Pedal:
            self.__axis_peak[trigger_type] = self.__axis_value[trigger_type]

    async def input_queue_loop(self):
        """Queue inputs from this device for next retrieval.
        """
        async for event in self._source.device_events_loop():
            # Ignore non-absolute events
            if event.type != evdev.ecodes.EV_ABS:
                continue

            if self.DEBUG_TRIGGER_DETECT and event.value == evdev_driver.AbsInputDevice.AXIS_MAX:
                print("Device: {0}, event: {1} [{2}]".format(self._source.name, evdev.ecodes.ABS[event.code], str(event)))

            # Limit to axis
            # Track maximum value, allowing for quick taps
            if event.code in self.__axis_codes[self.Pedal.GAS]:
                self.__axis_value[self.Pedal.GAS] = event.value
                self.__update_peaks()
            elif event.code in self.__axis_codes[self.Pedal.BRAKE]:
                self.__axis_value[self.Pedal.BRAKE] = event.value
                self.__update_peaks()
            elif event.code in self.__axis_codes[self.Pedal.CLUTCH]:
                self.__axis_value[self.Pedal.CLUTCH] = event.value
                self.__update_peaks()

    def retrieve_inputs(self):
        """Take the queued input values from this input device.

        Returns list of 0-1 decimal values representing haptics intensities
        """
        axis_max = evdev_driver.AbsInputDevice.AXIS_MAX
        # Gas + brake
        # [self.__axis_peak[self.Pedal.GAS] / axis_max, self.__axis_peak[self.Pedal.BRAKE] / axis_max]
        # Gas + brake + clutch
        # [self.__axis_peak[self.Pedal.GAS] / axis_max, self.__axis_peak[self.Pedal.BRAKE] / axis_max, self.__axis_peak[self.Pedal.CLUTCH] / axis_max]
        # Brake + clutch + gas
        result = [self.__axis_peak[self.Pedal.BRAKE] / axis_max, self.__axis_peak[self.Pedal.CLUTCH] / axis_max, self.__axis_peak[self.Pedal.GAS] / axis_max]
        self.__reset_peaks()
        return result


class SenderManager():

    class Config():
        HELP = "HELP"
        OPT_INITIAL_NAME = "# device name"
        OPT_MODE = "mode"
        MODE_IGNORED = "ignored"
        MODE_ANALOG_TRIGGERS = "analog_triggers"
        MODE_ANALOG_PEDALS = "analog_pedals"
        OPT_ORDER = "order"

    def __init__(self, config_file):
        self.__logger = logging.getLogger(__name__)
        self.__recorder = None
        self.reset_config()
        self.__config_file_path = config_file

    def on_haptics_request_cb(self):
        outputs = []

        try:
            # Get all feedback mapper entries
            # List is already sorted on load
            for feedback_mapper in self.__feedback_mappers:
                outputs.extend(feedback_mapper.retrieve_inputs())
        except AttributeError:
            # During shutdown, this callback may be called while the class is being destroyed
            # Safeguard against this by returning the default value
            pass

        return outputs

    def filter_device_id(self, device_id):
        return device_id.replace("=", "_").lower()

    def reset_config(self):
        # Clear state
        self.__feedback_mappers = []

    def write_sample_config(self):
        config = configparser.ConfigParser(delimiters = "=", allow_no_value=True)
        config[self.Config.HELP] = {}
        config_help = config[self.Config.HELP]
        # Uses allow_no_value=True
        config.set(self.Config.HELP, "# guide:")
        config.set(self.Config.HELP, "# [filtered name of device]")
        config.set(self.Config.HELP, "# " + self.Config.OPT_MODE + " = input mode (" + ", ".join((self.Config.MODE_IGNORED, self.Config.MODE_ANALOG_TRIGGERS, self.Config.MODE_ANALOG_PEDALS)) + ")")
        config.set(self.Config.HELP, "# " + self.Config.OPT_ORDER + " = relative order in haptics output, starting from 0")
        index = 0
        abs_input_devices = evdev_driver.get_abs_devices()
        if not len(abs_input_devices):
            self.__logger.warning("No absolute input devices connected")
        # Assign in order, to hopefully match haptics device physical order
        abs_input_devices.sort()
        for abs_input_device in abs_input_devices:
            filtered_device_id = self.filter_device_id(abs_input_device.id)
            config[filtered_device_id] = {}
            config_device = config[filtered_device_id]
            config_device[self.Config.OPT_INITIAL_NAME] = abs_input_device.name
            config_device[self.Config.OPT_MODE] = self.Config.MODE_IGNORED
            config_device[self.Config.OPT_ORDER] = str(index)
            index += 1

        # Make sure configuration directory exists
        os.makedirs(os.path.dirname(self.__config_file_path), exist_ok=True)
        # Save config
        with open(self.__config_file_path, 'w') as configfile:
            config.write(configfile)
        self.__logger.debug("Configuration file written to '{0}'".format(self.__config_file_path))

    def load_config(self):
        self.reset_config()

        # Load configuration
        config = configparser.ConfigParser(delimiters = "=")
        config.read(self.__config_file_path)
        abs_input_devices = evdev_driver.get_abs_devices()
        if not len(abs_input_devices):
            self.__logger.warning("No absolute input devices connected")

        for abs_input_device in abs_input_devices:
            filtered_device_id = self.filter_device_id(abs_input_device.id)
            if filtered_device_id in config:
                # Determine priority and input mode
                config_device = config[filtered_device_id]
                mode = config_device[self.Config.OPT_MODE]
                order = int(config_device[self.Config.OPT_ORDER])
                if mode == self.Config.MODE_IGNORED:
                    self.__logger.debug("Ignoring device '{0}' as requested".format(filtered_device_id))
                elif mode == self.Config.MODE_ANALOG_TRIGGERS:
                    self.__logger.debug("Mapping device '{0}' as analog triggers, ordered as '{1}'".format(filtered_device_id, order))
                    self.__feedback_mappers.append(FeedbackMapperAnalogTrigger(abs_input_device, order))
                elif mode == self.Config.MODE_ANALOG_PEDALS:
                    self.__logger.debug("Mapping device '{0}' as analog pedals, ordered as '{1}'".format(filtered_device_id, order))
                    self.__feedback_mappers.append(FeedbackMapperAnalogPedal(abs_input_device, order))
                else:
                    self.__logger.debug("Invalid mode '{1}' for device '{0}'".format(filtered_device_id, mode))
                    return False
            else:
                self.__logger.debug("Ignoring unconfigured device '{0}' ({1})".format(filtered_device_id, abs_input_device.name))

        if not len(self.__feedback_mappers):
            self.__logger.warning("No absolute input devices configured, check configuration file '{0}' or write a new one with '--write'".format(self.__config_file_path))
            return False

        # Important: sort the feedback mappers by priority/order
        self.__feedback_mappers.sort()

        self.__logger.debug("Configuration file read from '{0}'".format(self.__config_file_path))
        return True


    async def input_queue_loop(self):
        """Queue up inputs from all configured input devices
        """
        # Fetch the input queue loop from each feedback mapper and wait for all of them
        try:
            await asyncio.wait([feedback.input_queue_loop() for feedback in self.__feedback_mappers])
        except asyncio.CancelledError:
            # If used asynchronously, evdev devices need deleted afterwards to avoid "Exception ignored in"
            del self.__feedback_mappers

class PlayerManager():
    def __init__(self, recording_file, on_remark_processed_cb, on_status_request_cb, on_exit_request_cb):
        self.__logger = logging.getLogger(__name__)
        self.__recording_file = os.path.abspath(recording_file)
        self.__recording_base_dir = os.path.dirname(self.__recording_file)
        self.__on_remark_processed_cb = on_remark_processed_cb
        self.__on_status_request_cb = on_status_request_cb
        self.__on_exit_request_cb = on_exit_request_cb
        # Organize media player by ID
        self.__media_players = {}
        self.__sync_media_timer = None
        self.__feedback_mapper = FeedbackMapperPlayback(self.__recording_file, self.__on_remark_processed_cb, self.__on_media_processed_cb)
        self.__first_request = True

    def on_haptics_request_cb(self):
        # Get all feedback mapper entries
        if self.__first_request:
            self.__logger.debug("Playback stream connected")
            self.__first_request = False
        return self.__feedback_mapper.retrieve_inputs()

    def play(self):
        self.__feedback_mapper.play()
        self.__sync_media()

    def pause(self):
        self.__feedback_mapper.pause()
        self.__sync_media()

    @property
    def paused(self):
        return self.__feedback_mapper.paused

    @paused.setter
    def paused(self, value):
        if not value and self.paused:
            # Paused = false, currently paused, press play
            self.play()
        if value and not self.paused:
            # Paused = true, currently playing, press pause
            self.pause()

    @property
    def recording_start(self):
        return self.__feedback_mapper.recording_start

    @property
    def position(self):
        return self.__feedback_mapper.position

    @position.setter
    def position(self, value):
        #self.__logger.debug("Seeking to {0}".format(value))
        self.__feedback_mapper.position = value
        self.__sync_media()

    @property
    def position_formatted(self):
        return self.__feedback_mapper.position_formatted

    async def input_queue_loop(self):
        """Queue up inputs from all configured input devices
        """
        # Fetch the input queue loop from feedback mapper and wait
        #await asyncio.wait(self.__feedback_mapper.input_queue_loop())
        self.__logger.debug("Playing from recording '{0}'".format(self.__recording_file))
        canceled = False
        try:
            await self.__feedback_mapper.input_queue_loop()
        except asyncio.CancelledError:
            self.__logger.debug("Canceling playback")
            canceled = True
        finally:
            # Shut down all media players
            # For whatever reason, when canceled via console exit (instead of keyboard interrupt), normal shutdown doesn't work
            self.cleanup_media(canceled)
            self.__logger.debug("Playback finished")

    def cleanup_media(self, force_shutdown):
        # Shut down all media players
        for player in self.__media_players.values():
            player.quit(force_shutdown)
        self.__media_players.clear()

    def __on_media_processed_cb(self, media_command):
        if not media_command.id in self.__media_players:
            # Create new media player if none exists
            # NOTE: This results in churn if a stop command is sent for an exited or non-existent player ID
            self.__media_players[media_command.id] = MediaPlayer(self.__recording_base_dir, self.__external_paused_set_cb, self.__external_position_set_cb, self.__external_quit_cb)

        if isinstance(media_command, recording.EntryMediaStop):
            # Quit and delete the media player
            self.__media_players[media_command.id].quit(False)
            del self.__media_players[media_command.id]
        elif isinstance(media_command, recording.EntryMediaPlay):
            # Play with offset and time_delta
            # offset = 0 means that at time_delta, it should be starting 0s
            self.__media_players[media_command.id].play_with_offset(media_command.time_delta, media_command.offset, media_command.media_file)
        else:
            raise Exception("Unexpected/invalid media command: {0}".format(media_command))

        # Sync all players
        self.__sync_media_timer_cb()

    def __sync_media(self):
        for player in self.__media_players.values():
            player.sync(self.paused, self.position)

    def __sync_media_timer_cb(self):
        if not len(self.__media_players):
            # Stop if no media
            return

        self.__sync_media()

        if self.__sync_media_timer:
            # Cancel redundant timers
            self.__sync_media_timer.cancel()

        # Schedule again
        self.__sync_media_timer = asyncio.get_event_loop().call_later(haptics.MEDIA_SYNC_RATE_SECS, self.__sync_media_timer_cb)

    def __external_paused_set_cb(self, paused):
        self.paused = paused
        if self.__on_status_request_cb:
            self.__on_status_request_cb()

    def __external_position_set_cb(self, position):
        self.position = max(0, position)
        if self.__on_status_request_cb:
            self.__on_status_request_cb()

    def __external_quit_cb(self):
        self.__logger.debug("Exit requested by external program")
        if self.__on_exit_request_cb:
            self.__on_exit_request_cb()
