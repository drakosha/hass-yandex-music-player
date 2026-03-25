"""Constants for Yandex Music Player."""

DOMAIN = "yandex_music_player"
YANDEX_STATION_DOMAIN = "yandex_station"

CONF_TARGET_PLAYER = "target_player"
CONF_YANDEX_STATION_ENTRY = "yandex_station_entry"

# Media content types for browse/play
MEDIA_TYPE_YANDEX = "yandex"
MEDIA_TYPE_TRACK = "ym_track"
MEDIA_TYPE_ALBUM = "ym_album"
MEDIA_TYPE_PLAYLIST = "ym_playlist"
MEDIA_TYPE_ARTIST = "ym_artist"
MEDIA_TYPE_RADIO = "ym_radio"
MEDIA_TYPE_LIBRARY = "ym_library"
MEDIA_TYPE_SEARCH = "ym_search"

# Library sections
LIBRARY_PLAYLISTS = "playlists"
LIBRARY_LIKED = "liked"
LIBRARY_ALBUMS = "albums"
LIBRARY_ARTISTS = "artists"
LIBRARY_RADIO = "radio"

# Playback modes
REPEAT_OFF = "off"
REPEAT_ONE = "one"
REPEAT_ALL = "all"

# Default values
DEFAULT_CODEC = "mp3"
DEFAULT_BITRATE = 192
URL_REFRESH_MARGIN = 30  # seconds before URL expiry to refresh
LIKED_TRACKS_LIMIT = 500

# Events
EVENT_QUEUE_UPDATED = f"{DOMAIN}_queue_updated"
