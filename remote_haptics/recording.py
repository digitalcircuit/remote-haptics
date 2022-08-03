"""
Copyright: (c) 2022, Shane Synan <digitalcircuit36939@gmail.com>
GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

@package RemoteHaptics
"""

import asyncio

# Logging
import logging

# Timestamps and rate limiting
import datetime

# Haptics configuration
from remote_haptics import haptics

# Parsed recording entries
from dataclasses import dataclass
from abc import ABC

# Class ordering
import functools


class Recording:
    ENCODING = "utf-8"
    HEADER_VERSION = "RemoteHapticsRecording:0.1"
    HEADER_TIMESTAMP = "@session_start:"
    FOOTER_TIMESTAMP = "@session_end:"
    LINE_REMARK = "text="
    LINE_MEDIA = "media="

    MEDIA_DEFAULT_ID = "DEFAULT"
    MEDIA_CMD_STOP = "stop"


# Converting local time to UTC
# datetime.datetime.fromisoformat("2022-05-27 23:28:57.104-04:00").astimezone(datetime.timezone.utc).isoformat(sep=" ", timespec="microseconds")

# Don't lose more than this amount of data
RECORDING_FLUSH_INTERVAL_SECS = 30
# Record duplicate values after this much time has passed
RECORDING_DUPLICATE_INTERVAL_SECS = 10 * 60

# NOTE: Duplicate values aren't sent until haptics.PERSIST_DURATION_SECS elapses
RECORDING_DUPLICATE_INTERVAL_SECS = max(
    0, RECORDING_DUPLICATE_INTERVAL_SECS - haptics.PERSIST_DURATION_SECS
)

# Insert an absolute timestamp as a comment at most this often
# NOTE: Timestamp won't be inserted if there are no new values
RECORDING_TIMESTAMP_INTERVAL_SECS = 60


@dataclass(frozen=True, slots=True)
@functools.total_ordering
class EntryAbstract(ABC):
    """Base class for an entry in the haptics recording"""

    session_start: datetime.datetime
    time_delta: float

    def __lt__(self, other):
        return self.time_delta < other.time_delta

    def to_datetime(self) -> datetime.datetime:
        return self.session_start + datetime.timedelta(seconds=self.time_delta)

    def to_record_str(self) -> str:
        # Include up to 6 digits (microseconds)
        return "{0}".format(round(self.time_delta, haptics.TIME_PRECISION_PLACES))

    def with_offset(self, offset):
        return EntryAbstract(
            self.session_start + datetime.timedelta(seconds=offset),
            self.time_delta + offset,
        )


@dataclass(frozen=True, slots=True)
class EntryInputs(EntryAbstract):
    """Recorded haptics values"""

    inputs: list[float]

    def to_record_str(self) -> str:
        return "{0}:{1}\n".format(
            super(EntryInputs, self).to_record_str(), ",".join(map(str, self.inputs))
        )

    def with_offset(self, offset):
        return EntryInputs(
            self.session_start + datetime.timedelta(seconds=offset),
            self.time_delta + offset,
            self.inputs,
        )


@dataclass(frozen=True, slots=True)
class EntryRemark(EntryAbstract):
    """Recorded haptics remark"""

    remark: str

    def to_record_str(self) -> str:
        return "{0}:{1}{2}\n".format(
            super(EntryRemark, self).to_record_str(), Recording.LINE_REMARK, self.remark
        )

    def with_offset(self, offset):
        return EntryRemark(
            self.session_start + datetime.timedelta(seconds=offset),
            self.time_delta + offset,
            self.remark,
        )


@dataclass(frozen=True, slots=True)
class EntryMediaAbstract(EntryAbstract):
    """Base class for a media entry in the haptics recording"""

    id: str

    def to_record_str(self) -> str:
        id_marker = ""
        if self.id != Recording.MEDIA_DEFAULT_ID:
            id_marker = "@{0}".format(self.id)
        return "{0}:{1}{2}".format(
            super(EntryMediaAbstract, self).to_record_str(),
            Recording.LINE_MEDIA,
            id_marker,
        )

    def with_offset(self, offset):
        return EntryMediaAbstract(
            self.session_start + datetime.timedelta(seconds=offset),
            self.time_delta + offset,
            self.id,
        )


@dataclass(frozen=True, slots=True)
class EntryMediaStop(EntryMediaAbstract):
    """Recorded media stop command"""

    def to_record_str(self) -> str:
        return "{0}:{1}\n".format(
            super(EntryMediaStop, self).to_record_str(), Recording.MEDIA_CMD_STOP
        )

    def with_offset(self, offset):
        return EntryMediaStop(
            self.session_start + datetime.timedelta(seconds=offset),
            self.time_delta + offset,
            self.id,
        )


@dataclass(frozen=True, slots=True)
class EntryMediaPlay(EntryMediaAbstract):
    """Recorded media stop command"""

    offset: float
    media_file: str

    def to_record_str(self) -> str:
        return "{0}:{1}:{2}\n".format(
            super(EntryMediaStop, self).to_record_str(), offset, media_file
        )

    def with_offset(self, offset):
        return EntryMediaPlay(
            self.session_start + datetime.timedelta(seconds=offset),
            self.time_delta + offset,
            self.id,
            self.offset,
            self.media_file,
        )


def get_entry_from_line(recording_start, line):
    # Parse line
    line_data = line.strip().split(":")

    # Time elapsed
    time_delta = float(line_data[0])

    # Get rest of content
    line_content = ":".join(line_data[1:])
    # Value vs remark
    if line_content.startswith(Recording.LINE_REMARK):
        # Text remark
        # > 42.1337:text=Here's a comment embedded into the recording itself even with = signs
        return EntryRemark(
            recording_start, time_delta, line_content[len(Recording.LINE_REMARK) :]
        )
    elif line_content.startswith(Recording.LINE_MEDIA):
        # Media command
        media_data = line_content.removeprefix(Recording.LINE_MEDIA).split(":")

        # Check if an ID is specified
        id = Recording.MEDIA_DEFAULT_ID
        if media_data[0].startswith("@"):
            id = media_data[0].removeprefix("@")
            del media_data[0]

        # Determine command
        if media_data[0] == Recording.MEDIA_CMD_STOP:
            # Stop media command
            # > 0.0:media=stop
            # > 0.0:media=@player1:stop
            return EntryMediaStop(recording_start, time_delta, id)
        else:
            # Play media command
            # > 0.0:media=-5.4321:/path/to/media.mp4
            # > 0.0:media=@player1:-5.4321:/path/to/music.mp3

            # +/- media playback offset from current timestamp
            media_offset = float(media_data[0])
            # Path to media file
            media_filename = ":".join(media_data[1:])
            return EntryMediaPlay(
                recording_start, time_delta, id, media_offset, media_filename
            )
    else:
        # Haptics values
        # > 13.335039:0.301961,1
        return EntryInputs(
            recording_start, time_delta, [float(i) for i in line_content.split(",")]
        )


class HapticsWriter:
    def __init__(self, filename):
        self.__logger = logging.getLogger(__name__)
        time_now = datetime.datetime.now(datetime.timezone.utc)
        time_earliest = datetime.datetime(
            datetime.MINYEAR, 1, 1, tzinfo=datetime.timezone.utc
        )
        self.__session_start = time_now
        self.__flush_timer = None
        self.__last_haptics_entries = []
        self.__last_haptics_entries_duped = time_earliest
        self.__last_timestamp_comment = time_earliest
        self.__file_writer = open(filename, mode="w", encoding=Recording.ENCODING)
        self.__file_writer.write(Recording.HEADER_VERSION + "\n")
        self.__file_writer.write(
            Recording.HEADER_TIMESTAMP
            + time_now.isoformat(sep=" ", timespec=haptics.TIME_PRECISION_ISO)
            + "\n"
        )
        self.__flush_file_timer_cb()

    def append_record(self, haptics_entries):
        time_now = datetime.datetime.now(datetime.timezone.utc)
        time_delta = (time_now - self.__session_start).total_seconds()

        if (
            haptics_entries != self.__last_haptics_entries
            or (time_now - self.__last_haptics_entries_duped).total_seconds()
            > RECORDING_DUPLICATE_INTERVAL_SECS
        ):
            # Not duplicate or time elapsed, save

            # Insert UTC timestamp comment if not recently done
            if (
                time_now - self.__last_timestamp_comment
            ).total_seconds() > RECORDING_TIMESTAMP_INTERVAL_SECS:
                self.__file_writer.write(
                    "# timestamp = {0}\n".format(
                        time_now.isoformat(sep=" ", timespec=haptics.TIME_PRECISION_ISO)
                    )
                )
                self.__last_timestamp_comment = time_now

            # Save actual haptics data
            self.__file_writer.write(
                EntryInputs(
                    self.__session_start, time_delta, haptics_entries
                ).to_record_str()
            )
            # This could be written directly more efficiently, but it's probably better to keep it in sync with the event class
            # > "{0}:{1}\n".format(time_delta, ",".join(map(str, haptics_entries)))
            self.__last_haptics_entries = haptics_entries[:]
            self.__last_haptics_entries_duped = time_now

    def __flush_file_timer_cb(self):
        if not self.__file_writer.closed:
            self.__file_writer.flush()
            self.__flush_timer = asyncio.get_event_loop().call_later(
                RECORDING_FLUSH_INTERVAL_SECS, self.__flush_file_timer_cb
            )

    def close(self):
        # Record end time, too
        time_now = datetime.datetime.now(datetime.timezone.utc)
        self.__file_writer.write(
            Recording.FOOTER_TIMESTAMP
            + time_now.isoformat(sep=" ", timespec=haptics.TIME_PRECISION_ISO)
            + "\n"
        )
        self.__file_writer.close()


@functools.total_ordering
class HapticsReader:
    def __init__(self, filename, on_playback_finished):
        self.__logger = logging.getLogger(__name__)
        self.__on_playback_finished = on_playback_finished
        self.__reached_end = False
        self.__file_reader = open(filename, mode="r", encoding=Recording.ENCODING)
        self.__prev_time_delta = 0
        self.__current_record = None
        self.__restart()

    def __lt__(self, other):
        # Sort by start time
        return self.recording_start < other.recording_start

    @property
    def recording_start(self):
        return self.__start

    @property
    def reached_end(self):
        return self.__reached_end

    def __restart(self):
        # Go to beginning
        self.__prev_time_delta = 0
        self.__current_record = None
        self.__file_reader.seek(0)

        # Check for header version
        first_line = self.__file_reader.readline()
        if first_line.strip() != Recording.HEADER_VERSION:
            raise Exception(
                "Invalid recording file, header version is not the first line!  First line: {}".format(
                    first_line
                )
            )

        # Check for header timestamp
        timestamp_line = self.__file_reader.readline()
        if not timestamp_line.startswith(Recording.HEADER_TIMESTAMP):
            raise Exception(
                "Invalid recording file, header timestamp is not the second line!  Second line: {}".format(
                    timestamp_line
                )
            )
        # Parse header timestamp
        timestamp_str = timestamp_line[len(Recording.HEADER_TIMESTAMP) :].strip()
        self.__start = datetime.datetime.fromisoformat(timestamp_str)

    def delta_to_datetime(self, time_delta) -> datetime.datetime:
        if not isinstance(time_delta, datetime.timedelta):
            # Convert seconds to timedelta
            time_delta = datetime.timedelta(seconds=time_delta)
        return self.recording_start + time_delta

    def get_next_record(self):
        # Assume no record available
        record = None

        while not self.__reached_end:
            line = self.__file_reader.readline()
            if line == "" or line.startswith(Recording.FOOTER_TIMESTAMP):
                # Assume end of file (could also be a blank line)
                self.__reached_end = True
                if self.__on_playback_finished:
                    # Future is set, mark as finished
                    try:
                        self.__on_playback_finished.set_result(True)
                    except asyncio.exceptions.InvalidStateError:
                        # Ignore error, probably shutting down anyways
                        pass
                # Stop loop
                break
            elif line.startswith("#"):
                # Ignore comments
                continue

            # Parse line into an Entry[...]
            record = get_entry_from_line(self.recording_start, line)

            # Record found, stop loop
            break

        return record

    def get_records_until(self, time_delta, max_prev_seconds=3):
        if time_delta < self.__prev_time_delta:
            # Seeking backwards, restart from beginning
            self.__restart()
        # Mark current time delta
        self.__prev_time_delta = time_delta

        records = []

        # Store media events separately so seeking large gaps of time works as expected
        records_pruned_media = {}

        # Fast-forward to the current time if needed
        # If not at the end, keep trying as long as next record doesn't exist or it is earlier than time delta
        while not self.__reached_end and (
            not self.__current_record or self.__current_record.time_delta < time_delta
        ):
            # Include previous record if existing
            if self.__current_record:
                records.append(self.__current_record)

            while len(records) and records[0].time_delta < (
                time_delta - max_prev_seconds
            ):
                # Prune records more than max_prev_seconds older than time_delta
                if isinstance(records[0], EntryMediaAbstract):
                    # If it's a media record, track the most recent event by ID
                    records_pruned_media[records[0].id] = records[0]

                # Delete record
                del records[0]

            record = self.get_next_record()
            if not record:
                # Reached end
                break

            # Store this record for the next iteration (the time_delta might be far in the future)
            self.__current_record = record
            # Loop again

        # If media events were pruned, process them
        if len(records_pruned_media):
            # Add all pruned records to the list
            records.extend(records_pruned_media.values())
            # Sort according to time
            records.sort()

        # Return result
        return records

    def close(self):
        self.__reached_end = True
        self.__file_reader.close()


def merge_recordings(output_filename, recording_filenames):
    logger = logging.getLogger(__name__)

    readers = []

    # Load recordings
    for recording_filename in recording_filenames:
        readers.append(HapticsReader(recording_filename, None))

    if not readers:
        logger.error("No recordings given, cannot merge!")
        return

    # Prepare offsets and record entries
    offsets = [None] * len(readers)
    reader_entries = [None] * len(readers)

    # Sort to find the earliest recording
    readers.sort()
    earliest_recording_start = readers[0].recording_start

    # Find the offset between the earliest recording start and each recording
    for index in range(0, len(readers)):
        offsets[index] = (
            readers[index].recording_start - earliest_recording_start
        ).total_seconds()

    # Start output file
    file_writer = open(output_filename, mode="w", encoding=Recording.ENCODING)
    file_writer.write(Recording.HEADER_VERSION + "\n")
    file_writer.write(
        Recording.HEADER_TIMESTAMP
        + earliest_recording_start.isoformat(
            sep=" ", timespec=haptics.TIME_PRECISION_ISO
        )
        + "\n"
    )

    # Track the ending delta
    ending_time_delta = -1

    # Merge all readers
    while True:
        for index in range(0, len(readers)):
            if not reader_entries[index]:
                # Fetch next record since the previous one was used up
                reader_entries[index] = readers[index].get_next_record()
                # Apply offset if record exists
                if reader_entries[index]:
                    reader_entries[index] = reader_entries[index].with_offset(
                        offsets[index]
                    )

        # Check every item for the oldest
        oldest_delta = None
        oldest_index = -1
        for index in range(0, len(readers)):
            if not reader_entries[index]:
                continue

            if oldest_delta is None or (
                reader_entries[index].time_delta < oldest_delta
            ):
                # No record exists, or an older record was found
                oldest_index = index
                oldest_delta = reader_entries[index].time_delta

        if oldest_delta is None:
            # No record found, exit loop
            break

        # Update ending time
        ending_time_delta = oldest_delta

        # Save the oldest item
        file_writer.write(reader_entries[oldest_index].to_record_str())
        # Clear item as it's been written out
        reader_entries[oldest_index] = None

    # Record end time, too
    # Calculate via start + ending (biggest) delta
    last_recording_end = earliest_recording_start + datetime.timedelta(
        seconds=ending_time_delta
    )
    file_writer.write(
        Recording.FOOTER_TIMESTAMP
        + last_recording_end.isoformat(sep=" ", timespec=haptics.TIME_PRECISION_ISO)
        + "\n"
    )
    file_writer.close()
