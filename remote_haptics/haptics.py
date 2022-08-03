"""
Copyright: (c) 2022, Shane Synan <digitalcircuit36939@gmail.com>
GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

@package RemoteHaptics
"""

# Extra debug verbosity
# > API and protocol debugging
VERBOSE_API = False
# > Media player debugging
VERBOSE_MEDIA = False
# > Receiver physics simulation debugging
VERBOSE_RECEIVER_PHYSICS = False

# How long in seconds to keep the haptics input/output active without updates
PERSIST_DURATION_SECS = 15

# How long in seconds to try to wait between haptics updates
# This limits network traffic and physics calculation updates
#
# 60 FPS (feedbacks per second) should be good
MAX_UPDATE_RATE_SECS = 1 / 60

# Default network port number if not specified
# First step towards standardization
NET_DEFAULT_PORT = 7837

# Precision used when saving timestamps (e.g. recording start)
TIME_PRECISION_ISO = "microseconds"
TIME_PRECISION_PLACES = 6

# If media is playing, how often to sync media players to the haptics playback
MEDIA_SYNC_RATE_SECS = 0.5

# Allowed difference between the media playback position and the haptics playback position
MEDIA_POSITION_SKEW_SECS = 0.15
