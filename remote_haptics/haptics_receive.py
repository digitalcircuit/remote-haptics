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

# Math for physics
import math

# Haptics setup
from remote_haptics import haptics

# Rumble output
from remote_haptics import evdev_driver

# Recording
from remote_haptics import recording

# Session types
from remote_haptics.api import SessionType

# Configuration file
import configparser

class FeedbackMapper():
    def __init__(self, haptics_input_ids, haptics_input_ids_override, haptics_outputs):
        """Initialize a feedback mapping between inputs and outputs.

        haptics_input_ids: List of haptics input IDs (indices) to use
        haptics_input_ids_override: List of haptics input IDs (indices) that skip averaging (1.0 input = 1.0 output)
        haptics_outputs: Collection of rumble devices to control
        """
        self.__logger = logging.getLogger(__name__)
        self.__previous_time = None
        self.__previous_value = 0
        #self.__previous_value_delta = 0
        self.__physics_timer = None
        self.__physics_calc_impact = 0
        self.__physics_calc_impact_boost = 0
        self.__physics_calc_avg_value = 0
        self.__input_ids = haptics_input_ids
        self.__input_ids_override = haptics_input_ids_override
        self.__outputs = haptics_outputs

    def apply_outputs(self, strong_intensity, weak_intensity):
        """Set the haptics outputs to the specified intensities.

        strong_intensity: 0.0-1.0 scale for strong haptics feedback
        weak_intensity: 0.0-1.0 scale for weak haptics feedback
        """

        # Scale from 0.0-1.0 mapping
        strong_magnitude = int(max(0, min(evdev_driver.RumbleDevice.RUMBLE_MAX * strong_intensity, evdev_driver.RumbleDevice.RUMBLE_MAX)))
        weak_magnitude = int(max(0, min(evdev_driver.RumbleDevice.RUMBLE_MAX * weak_intensity, evdev_driver.RumbleDevice.RUMBLE_MAX)))
        for rumble_device in self.__outputs:
            rumble_device.rumble(duration_ms=haptics.PERSIST_DURATION_SECS * 1000, strong_magnitude=strong_magnitude, weak_magnitude=weak_magnitude)

    def parse_inputs(self, haptics_inputs):
        """Parse the given list of haptics inputs, ignoring non-matching inputs.

        If no matching values exist, nothing will be changed.

        haptics_inputs: List of 0-1 decimal values representing haptics intensities
        """
        # None or empty list turns off output
        if not haptics_inputs:
            self.__physics_interrupt()
            return

        value = 0
        matches = 0
        for index in self.__input_ids:
            if index < len(haptics_inputs):
                value += haptics_inputs[index]
                matches += 1

        # Check if any override index is valid
        for index in self.__input_ids_override:
            if matches > 0:
                # No need to keep checking
                break
            if index < len(haptics_inputs):
                # Match found - increment match to 1
                if matches < 1:
                    matches = 1

        # Bail out if nothing matches
        if matches < 1:
            self.__logger.error("No matching haptics inputs found!  Haptics input count: {0}, requested IDs/indices: {1} (override/full: {2})".format(len(haptics_inputs), self.__input_ids, self.__input_ids_override))
            self.__physics_interrupt()
            return

        # Take the average
        value = value / matches

        # Apply override indices
        for index in self.__input_ids_override:
            if index < len(haptics_inputs):
                # Take the maximum value
                value = max(value, haptics_inputs[index])

        self.__physics_update(value)

    def __physics_interrupt(self):
        if self.__physics_timer:
            self.__physics_timer.cancel()
            self.__physics_timer = None
        self.apply_outputs(0, 0)

    def __physics_update(self, value):
        # Apply physics over time
        # Assume an excess amount of time has passed if not specified
        time_delta = haptics.PERSIST_DURATION_SECS * 2
        if self.__previous_time:
            time_delta = (datetime.datetime.now(datetime.timezone.utc) - self.__previous_time).total_seconds()

        # Process physics
        output_strong = 0
        output_weak = value

        # Placeholder invalid value
        value_delta = 0.1337
        #value_accel = 0.1337
        # If slow (1.2 / 1 = 1.2), increase impact
        # If fast (0.8 / 1 = 0.8), decrease impact
        time_ratio = (time_delta / haptics.MAX_UPDATE_RATE_SECS)

        avg_percent_old = 0.75 + time_ratio
        self.__physics_calc_avg_value = (value * avg_percent_old) + (self.__physics_calc_avg_value * (1 - avg_percent_old))

        avg_value_delta = abs(value - self.__physics_calc_avg_value)
        if avg_value_delta < 0.001:
            # Snap average to value if close enough
            self.__physics_calc_avg_value = value
            avg_value_delta = 0

        if time_delta <= haptics.PERSIST_DURATION_SECS:
            # Within maximum latency, update physics calculations
            value_delta = abs((value - self.__previous_value) / time_ratio)
            #self.__physics_calc_impact = value_delta + avg_value_delta
            # Reduce small numbers, amplify large numbers
            self.__physics_calc_impact = math.pow(value_delta + avg_value_delta, 3)
            if self.__physics_calc_impact > 250:
                # Boost impact for strong numbers
                self.__physics_calc_impact_boost = min(7, self.__physics_calc_impact * 0.2 * time_ratio)
            else:
                # Decrement impact boost on weaker numbers
                self.__physics_calc_impact_boost = max(0, self.__physics_calc_impact_boost - (time_ratio / 2))
                # Edit: "- time_ratio" -> "- (time_ratio / 2)"
                if self.__physics_calc_impact_boost < 0.01:
                    # Snap to zero
                    self.__physics_calc_impact_boost = 0
            if self.__physics_calc_impact_boost > 0:
                self.__physics_calc_impact = max(1, self.__physics_calc_impact)
        else:
            # Too long of a gap, ignore physics
            if haptics.VERBOSE_RECEIVER_PHYSICS:
                self.__logger.debug("More than {0}s elapsed ({1}s), ignoring physics".format(haptics.PERSIST_DURATION_SECS, time_delta))

        output_strong = min(1, max(0, self.__physics_calc_impact))
        # Reduce weak rumble by impact rumble
        output_weak = max(0, output_weak - (output_strong * 0.5))

        if haptics.VERBOSE_RECEIVER_PHYSICS:
            print("Physics {0} = val: {1: >5.4f}, delta: {2: >9.4f}, avg: {3: >9.4f}, avg_delta: {4: >9.4f}, boost: {5: >6.2f}, impact: {6: >11.4f}, weak: {7: >5.4f}, strong: {8: >5.4f}".format(self.__input_ids, value, value_delta, self.__physics_calc_avg_value, avg_value_delta, self.__physics_calc_impact_boost, self.__physics_calc_impact, output_weak, output_strong), flush=True)

        self.apply_outputs(output_strong, output_weak)

        # Update previous records with this event
        self.__previous_value = value
        self.__previous_time = datetime.datetime.now(datetime.timezone.utc)

        if self.__physics_calc_impact > 0 or self.__physics_calc_impact_boost > 0 or avg_value_delta > 0:
            # Not finished processing, schedule another update
            if not self.__physics_timer:
                self.__physics_timer = asyncio.get_event_loop().call_later(haptics.MAX_UPDATE_RATE_SECS, self.__physics_timer_cb)

    def __physics_timer_cb(self):
        self.__physics_timer = None
        self.__physics_update(self.__previous_value)


class ReceiverManager():
    class Config():
        RECORDING = "recording"
        RECORDING_OPT_ENABLED = "enabled"
        RECORDING_OPT_DEST_DIR = "destination_dir"
        DEVICES = "devices"
        OPT_INITIAL_NAME_FORMAT = "# '{0}'"

    def __init__(self, config_file):
        self.__logger = logging.getLogger(__name__)
        self.__recorder = None
        self.reset_config()
        self.__config_file_path = config_file

    def on_session_new_cb(self, peername):
        # Finish existing recording, if it exists
        self.recording_end()

    def on_session_end_cb(self, peername):
        # Finish existing recording, if it exists
        self.recording_end()
        # Clear haptics
        self.on_haptics_updated_cb(None)

    def on_session_type_set_cb(self, peername, session_type):
        if session_type == SessionType.LIVE:
            # Record live sessions
            self.recording_start(peername)
        else:
            # Ignore other sessions
            self.recording_end()

    def on_haptics_updated_cb(self, haptics_entries):
        # Send to output
        for feedback_mapper in self.__feedback_mappers:
            feedback_mapper.parse_inputs(haptics_entries)
        # Update recording
        if self.__recording_enabled and self.__recorder:
            self.__recorder.append_record(haptics_entries)

    def filter_device_id(self, device_id):
        return device_id.replace("=", "_").lower()

    def recording_start(self, peername):
        if not self.__recording_enabled:
            return
        # Finish existing recording, if it exists
        self.recording_end()
        # Ensure recording directory exists
        os.makedirs(self.__recording_dir, exist_ok = True)
        # Format filename
        # See https://stackoverflow.com/questions/7406102/create-sane-safe-filename-from-any-unsafe-string
        keepcharacters = (' ','.','_')
        peerhost = peername[0]
        peerhost_safe = "".join(c for c in peerhost if c.isalnum() or c in keepcharacters).rstrip()
        datetimestamp = datetime.datetime.now().strftime("%F %H-%M-%S")
        recording_peer_dir = os.path.join(self.__recording_dir, peerhost_safe)
        os.makedirs(recording_peer_dir, exist_ok = True)
        record_file = os.path.join(recording_peer_dir, datetimestamp + ".rec")
        # Start new recording
        self.__recorder = recording.HapticsWriter(record_file)
        self.__logger.debug("Recording new session to '{0}'".format(record_file))

    def recording_end(self):
        if self.__recorder:
            self.__logger.debug("Recording ended")
            self.__recorder.close()
            self.__recorder = None

    def reset_config(self):
        # Clear state
        self.__feedback_mappers = []
        self.__recording_enabled = False
        self.__recording_dir = ""

    def write_sample_config(self):
        config = configparser.ConfigParser(delimiters = "=", allow_no_value=True)
        config[self.Config.RECORDING] = {}
        config_recording = config[self.Config.RECORDING]
        config_recording[self.Config.RECORDING_OPT_ENABLED] = False
        config_recording[self.Config.RECORDING_OPT_DEST_DIR] = "recordings"
        config[self.Config.DEVICES] = {}
        config_devices = config[self.Config.DEVICES]
        # Uses allow_no_value=True
        config.set(self.Config.DEVICES, "# syntax:")
        config.set(self.Config.DEVICES, "# device = haptics input indices")
        config.set(self.Config.DEVICES, "# specify +number (e.g. +4) to exclude that index from averaging (1.0 is treated as full 1.0)")
        config.set(self.Config.DEVICES, "# sample_device = 0, 1, +4")
        index = 0
        rumble_devices = evdev_driver.get_rumble_devices()
        if not len(rumble_devices):
            self.__logger.warning("No rumble devices connected")
        # Assign in order, to hopefully match haptics device physical order
        rumble_devices.sort()
        for rumble_device in rumble_devices:
            filtered_device_id = self.filter_device_id(rumble_device.id)
            config_devices[self.Config.OPT_INITIAL_NAME_FORMAT.format(filtered_device_id)] = rumble_device.name
            config_devices[filtered_device_id] = str(index)
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
        if not "recording" in config:
            self.__logger.warning("Configuration file '{0}' doesn't specify recording mode, write a new one with '--write'?".format(self.__config_file_path))
            return False
        config_recording = config[self.Config.RECORDING]
        self.__recording_enabled = config_recording.getboolean(self.Config.RECORDING_OPT_ENABLED)
        self.__recording_dir = config_recording[self.Config.RECORDING_OPT_DEST_DIR]
        if self.__recording_enabled:
            self.__logger.debug("Recording live sessions enabled, saving to '{0}'".format(self.__recording_dir))
        else:
            self.__logger.debug("Recording disabled")

        if not "devices" in config:
            self.__logger.warning("Configuration file '{0}' doesn't specify any devices, write a new one with '--write'?".format(self.__config_file_path))
            return False
        config_devices = config[self.Config.DEVICES]
        rumble_devices = evdev_driver.get_rumble_devices()
        if not len(rumble_devices):
            self.__logger.warning("No rumble devices connected")

        for rumble_device in rumble_devices:
            filtered_device_id = self.filter_device_id(rumble_device.id)
            if filtered_device_id in config_devices:
                # Convert IDs to integer
                haptics_ids = config_devices[filtered_device_id]
                haptics_ids_normal = []
                haptics_ids_override = []
                for index in haptics_ids.split(","):
                    index = index.strip()
                    if index.startswith("+"):
                        haptics_ids_override.append(int(index[1:]))
                    else:
                        haptics_ids_normal.append(int(index))

                #haptics_ids = [int(i.strip()) for i in haptics_ids.split(",")]
                self.__logger.debug("Mapping device '{0}' to haptics indices '{1}' (overrides: '{2}')".format(filtered_device_id, haptics_ids_normal, haptics_ids_override))
                self.__feedback_mappers.append(FeedbackMapper(haptics_ids_normal, haptics_ids_override, [rumble_device]))
            else:
                self.__logger.debug("Ignoring unconfigured device '{0}' ({1})".format(filtered_device_id, rumble_device.name))

        if not len(self.__feedback_mappers):
            self.__logger.warning("No rumble devices configured, check configuration file '{0}' or write a new one with '--write'".format(self.__config_file_path))

        self.__logger.debug("Configuration file read from '{0}'".format(self.__config_file_path))
        return True
