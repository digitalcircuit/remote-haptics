'''
Copyright: (c) 2022, Shane Synan <digitalcircuit36939@gmail.com>
GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

@package RemoteHaptics
'''

import asyncio

# Logging
import logging

# Class ordering
import functools

import evdev

# See https://python-evdev.readthedocs.io/en/latest/tutorial.html
from evdev import ecodes, InputDevice, ff

@functools.total_ordering
class EvdevDevice:
    """A simple evdev device.
    """

    def __init__(self, evdev_device):
        self.__logger = logging.getLogger(__name__)
        self.__device = evdev_device

    def __del__(self):
        # If used asynchronously, evdev devices need deleted afterwards to avoid "Exception ignored in"
        self.__device.close()

    # See https://stackoverflow.com/questions/8796886/is-it-safe-to-just-implement-lt-for-a-class-that-will-be-sorted
    def __eq__(self, other):
        return (self.id == other.id)

    def __lt__(self, other):
        return (self.id < other.id)

    @property
    def name(self):
        """Get the device name
        """
        return self.__device.name

    @property
    def id(self):
        """Get the unique device identifier

        This may change when reconnecting devices.
        """
        return self.__device.phys

    @property
    def _device(self):
        """Get the device (meant for subclasses)
        """
        return self.__device

class RumbleDevice(EvdevDevice):
    """A simple evdev device capable of rumble output.
    """
    RUMBLE_MAX = 0xffff
    #RUMBLE_MIN = 0x0000
    # TODO: Fetch at runtime from AbsInfo class

    def __init__(self, evdev_device):
        super().__init__(evdev_device)
        self.__logger = logging.getLogger(__name__)
        self.__rumble_effect_id = None
        # Number of effects able to be stored: evdev_device.ff_effects_count

    def rumble(self, duration_ms, strong_magnitude, weak_magnitude):
        """Play a rumble effect, dynamically updating the current effect if it exists.
        """
        # Start new effect
        repeat_count = 1
        rumble = ff.Rumble(strong_magnitude=strong_magnitude, weak_magnitude=weak_magnitude)
        effect_type = ff.EffectType(ff_rumble_effect=rumble)
        effect_id = -1
        # -1 = new effect
        # same ID = dynamically update existing effect
        if self.__rumble_effect_id:
            effect_id = self.__rumble_effect_id
        effect = ff.Effect(
        ecodes.FF_RUMBLE, effect_id, 0,
            ff.Trigger(0, 0),
            ff.Replay(duration_ms, 0),
            effect_type
            #ff.EffectType(ff_rumble_effect=rumble)
        )
        self.__rumble_effect_id = self._device.upload_effect(effect)
        self._device.write(ecodes.EV_FF, self.__rumble_effect_id, repeat_count)

    def stop_rumble(self):
        if self.__rumble_effect_id:
            # Stop and clean up existing effect
            self._device.erase_effect(self.__rumble_effect_id)
            self.__rumble_effect_id = None

class AbsInputDevice(EvdevDevice):
    """A simple evdev device capable of absolute input (trigger, joystick, etc).
    """

    TRIGGER_MAX = 0xff
    #TRIGGER_MIN = 0x00
    AXIS_MAX = 0xff
    #AXIS_MIN = 0x00
    # TODO: Fetch at runtime from AbsInfo class

    def __init__(self, evdev_device):
        super().__init__(evdev_device)
        self.__logger = logging.getLogger(__name__)
        self.__rumble_effect_id = None
        # Number of effects able to be stored: evdev_device.ff_effects_count

    @property
    def device_events_loop(self):
        """Get the input events from the device.
        """
        return self._device.async_read_loop

def get_abs_devices():
    """Returns all evdev devices that are analog input (EV_ABS) capable.
    """
    # Find all EV_ABS capable event devices (that we have permissions to use).
    devices = []

    for name in evdev.list_devices():
        dev = InputDevice(name)
        if ecodes.EV_ABS in dev.capabilities():
            devices.append(AbsInputDevice(dev))
    return devices

def get_rumble_devices():
    """Returns all evdev devices that are force-feedback (EV_FF) capable.
    """
    # Find all EV_FF capable event devices (that we have permissions to use).
    devices = []

    for name in evdev.list_devices():
        dev = InputDevice(name)
        if ecodes.EV_FF in dev.capabilities():
            devices.append(RumbleDevice(dev))
    return devices
