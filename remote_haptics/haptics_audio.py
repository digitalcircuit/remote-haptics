"""
Copyright: (c) 2022, Shane Synan <digitalcircuit36939@gmail.com>
GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

@package RemoteHaptics
"""

import asyncio

# Logging
import logging

# Audio process
import os

# Timestamps
import datetime

# Haptics setup
from remote_haptics import haptics

# Abstract feedback mapper
from remote_haptics.haptics_send import FeedbackMapperAbstract

# Custom audio categories
from enum import Enum


class FeedbackMapperAudio(FeedbackMapperAbstract):
    AUDIO_DATA_HEADER = "audio_data:"
    # Treat audio levels as processed after this delay
    AUDIO_ROLLING_SAMPLE_SECS = 10 / 1000
    AUDIO_VOLUME_LOW_PERCENTAGE = 0
    AUDIO_VOLUME_MID_PERCENTAGE = 0.005
    AUDIO_VOLUME_HIGH_PERCENTAGE = 0.92

    class FrequencyBand(Enum):
        ALL = 0
        BASS = 1
        MID = 2
        TREBLE = 3

    def __init__(self, audio_mode):
        """Initialize a feedback mapping between audio and outputs."""
        super().__init__(None, 0)
        self.__logger = logging.getLogger(__name__)

        self.__audio_mode = None
        if audio_mode == "all":
            self.__audio_mode = self.FrequencyBand.ALL
        elif audio_mode == "bass":
            self.__audio_mode = self.FrequencyBand.BASS
        elif audio_mode == "mid":
            self.__audio_mode = self.FrequencyBand.MID
        elif audio_mode == "treble":
            self.__audio_mode = self.FrequencyBand.TREBLE
        else:
            raise Exception("Invalid audio mode '{0}'".format(audio_mode))

        self.__impulse_process = None
        self.__levels_rolling = []
        self.__levels_peak = {}
        self.__pop_rolling()
        self.__reset_peaks()

    def __pop_rolling(self):
        rolling = self.__levels_rolling[:]
        self.__levels_rolling = [0] * len(self.__levels_rolling)
        self.__levels_rolling_start = datetime.datetime.now(datetime.timezone.utc)
        return rolling

    def __reset_peaks(self):
        for freq_band in self.FrequencyBand:
            self.__levels_peak[freq_band] = 0

    async def input_queue_loop(self):
        """Queue inputs from this device for next retrieval."""
        impulse_path = os.path.join(os.path.dirname(__file__), "impulse-print")
        audio_levels = []
        self.__impulse_process = await asyncio.create_subprocess_exec(
            impulse_path,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
        )
        # Fetch Impulse audio
        while True:
            line = await self.__impulse_process.stdout.readline()
            message = line.decode().strip()
            if message.startswith(self.AUDIO_DATA_HEADER):
                message = message[len(self.AUDIO_DATA_HEADER) :].strip(",")
                audio_levels = [float(volume) for volume in message.split(",")]
                # Process audio levels
                if len(self.__levels_rolling) != len(audio_levels):
                    self.__levels_rolling = audio_levels[:]
                else:
                    for i in range(0, len(audio_levels)):
                        self.__levels_rolling[i] = max(
                            audio_levels[i], self.__levels_rolling[i]
                        )
                if (
                    datetime.datetime.now(datetime.timezone.utc)
                    - self.__levels_rolling_start
                ).total_seconds() > self.AUDIO_ROLLING_SAMPLE_SECS:
                    sample = self.__pop_rolling()
                    # Process into ranges
                    bar_1 = 0.0
                    bar_2 = 0.0
                    bar_3 = 0.0
                    i_volume_max = len(sample)
                    for i_volume in range(0, len(sample)):
                        i_volume_percent = i_volume / i_volume_max
                        if (
                            i_volume_percent >= self.AUDIO_VOLUME_LOW_PERCENTAGE
                            and i_volume_percent < self.AUDIO_VOLUME_MID_PERCENTAGE
                        ):
                            bar_1 = max(sample[i_volume], bar_1)
                        elif (
                            i_volume_percent >= self.AUDIO_VOLUME_MID_PERCENTAGE
                            and i_volume_percent < self.AUDIO_VOLUME_HIGH_PERCENTAGE
                        ):
                            bar_2 = max(sample[i_volume], bar_2)
                        else:
                            bar_3 = max(sample[i_volume], bar_3)
                    self.__levels_peak[self.FrequencyBand.BASS] = bar_1
                    self.__levels_peak[self.FrequencyBand.MID] = bar_2
                    self.__levels_peak[self.FrequencyBand.TREBLE] = bar_3
                    self.__levels_peak[self.FrequencyBand.ALL] = max(
                        min(
                            (
                                self.__levels_peak[self.FrequencyBand.BASS] * 0.25
                                + self.__levels_peak[self.FrequencyBand.MID] * 0.45
                                + self.__levels_peak[self.FrequencyBand.TREBLE] * 0.5
                            ),
                            1,
                        ),
                        0,
                    )
            else:
                continue

    def retrieve_inputs(self):
        """Take the queued input values from this input device.

        Returns list of 0-1 decimal values representing haptics intensities
        """
        result = [self.__levels_peak[self.__audio_mode]] * 2
        self.__reset_peaks()
        return result


class AudioManager:
    def __init__(self, audio_mode):
        self.__logger = logging.getLogger(__name__)
        self.__audio_mode_str = audio_mode
        self.__feedback_mapper = FeedbackMapperAudio(audio_mode)

    def on_haptics_request_cb(self):
        # Get all feedback mapper entries
        return self.__feedback_mapper.retrieve_inputs()

    async def input_queue_loop(self):
        """Queue up inputs from all configured input devices"""
        # Fetch the input queue loop from feedback mapper and wait
        # await asyncio.wait(self.__feedback_mapper.input_queue_loop())
        self.__logger.debug(
            "Streaming from audio using '{0}' mode".format(self.__audio_mode_str)
        )
        await self.__feedback_mapper.input_queue_loop()
        self.__logger.debug("Audio finished")
