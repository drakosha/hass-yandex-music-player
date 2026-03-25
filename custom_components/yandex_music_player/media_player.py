"""Yandex Music media player entity."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    RepeatMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_IDLE, STATE_PAUSED, STATE_PLAYING
from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)

from .api import YandexMusicAPI, track_title, track_image_url
from .const import (
    CONF_TARGET_PLAYER,
    DOMAIN,
    MEDIA_TYPE_ALBUM,
    MEDIA_TYPE_ARTIST,
    MEDIA_TYPE_PLAYLIST,
    MEDIA_TYPE_RADIO,
    MEDIA_TYPE_SEARCH,
    MEDIA_TYPE_TRACK,
    MEDIA_TYPE_YANDEX,
    REPEAT_ALL,
    REPEAT_OFF,
    REPEAT_ONE,
)
from .proxy import generate_proxy_url
from .queue import PlayQueue

_LOGGER = logging.getLogger(__name__)

SUPPORT_FEATURES = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.SHUFFLE_SET
    | MediaPlayerEntityFeature.REPEAT_SET
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.BROWSE_MEDIA
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
)

# Time between checks for track completion
POLL_INTERVAL = timedelta(seconds=3)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Yandex Music Player from config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    api: YandexMusicAPI = data["api"]
    target_player: str = entry.data[CONF_TARGET_PLAYER]

    entity = YandexMusicPlayerEntity(
        hass=hass,
        api=api,
        target_entity_id=target_player,
        entry_id=entry.entry_id,
    )
    async_add_entities([entity], True)


class YandexMusicPlayerEntity(MediaPlayerEntity):
    """A virtual media player that plays Yandex Music on any HA player."""

    _attr_has_entity_name = True
    _attr_name = "Yandex Music"
    _attr_supported_features = SUPPORT_FEATURES
    _attr_media_content_type = "music"

    def __init__(
        self,
        hass: HomeAssistant,
        api: YandexMusicAPI,
        target_entity_id: str,
        entry_id: str,
    ) -> None:
        self.hass = hass
        self._api = api
        self._target_entity_id = target_entity_id
        self._entry_id = entry_id
        self._queue = PlayQueue(api)

        self._attr_unique_id = f"ym_player_{entry_id}"
        self._target_media_type = self._detect_media_type()

        # State tracking
        self._state = MediaPlayerState.IDLE
        self._volume: float = 0.5
        self._muted: bool = False
        self._target_was_playing: bool = False
        self._unsub_state: Any = None
        self._unsub_poll: Any = None
        self._advancing: bool = False

    @property
    def state(self) -> MediaPlayerState:
        return self._state

    @property
    def volume_level(self) -> float:
        return self._volume

    @property
    def is_volume_muted(self) -> bool:
        return self._muted

    @property
    def media_content_id(self) -> str | None:
        item = self._queue.current
        return item.track_id if item else None

    @property
    def media_content_type(self) -> str | None:
        return "music"

    @property
    def media_title(self) -> str | None:
        item = self._queue.current
        if item and item.track:
            return item.track.title
        return None

    @property
    def media_artist(self) -> str | None:
        item = self._queue.current
        if item and item.track and item.track.artists:
            return ", ".join(
                a.name for a in item.track.artists if a.name
            )
        return None

    @property
    def media_album_name(self) -> str | None:
        item = self._queue.current
        if item and item.track and item.track.albums:
            album = item.track.albums[0]
            return album.title
        return None

    @property
    def media_duration(self) -> float | None:
        item = self._queue.current
        return item.duration if item else None

    @property
    def media_image_url(self) -> str | None:
        item = self._queue.current
        return item.image_url if item else None

    @property
    def shuffle(self) -> bool:
        return self._queue.shuffle

    @property
    def repeat(self) -> RepeatMode:
        r = self._queue.repeat
        if r == REPEAT_ONE:
            return RepeatMode.ONE
        if r == REPEAT_ALL:
            return RepeatMode.ALL
        return RepeatMode.OFF

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs = {
            "target_player": self._target_entity_id,
            "queue_length": len(self._queue.items),
            "queue_position": self._queue.position,
            "is_radio": self._queue.is_radio,
        }
        return attrs

    # ── Setup / Teardown ───────────────────────────────────────────

    async def async_added_to_hass(self) -> None:
        """Subscribe to target player state changes and auto-start My Wave."""
        self._unsub_state = async_track_state_change_event(
            self.hass, self._target_entity_id, self._on_target_state_change
        )
        # Auto-start "Моя волна" so there's something to play immediately
        self.hass.async_create_task(self._auto_start_my_wave())

    async def _auto_start_my_wave(self) -> None:
        """Load My Wave radio into the queue (without starting playback)."""
        try:
            await self._queue.load_radio("user:onyourwave")
            _LOGGER.debug("Auto-loaded My Wave into queue")
            self.async_write_ha_state()
        except Exception:
            _LOGGER.debug("Failed to auto-load My Wave", exc_info=True)

    async def async_will_remove_from_hass(self) -> None:
        """Clean up subscriptions."""
        if self._unsub_state:
            self._unsub_state()
        if self._unsub_poll:
            self._unsub_poll()

    # ── Target player interaction ──────────────────────────────────

    @callback
    def _on_target_state_change(self, event: Event) -> None:
        """React to target player state changes."""
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")

        if not new_state or not old_state:
            return

        new = new_state.state
        old = old_state.state

        # Track went from playing to idle => track finished
        if (
            old in (STATE_PLAYING, STATE_PAUSED)
            and new == STATE_IDLE
            and self._state == MediaPlayerState.PLAYING
            and not self._advancing
        ):
            self.hass.async_create_task(self._on_track_finished())

        # Sync volume from target
        if new_state.attributes.get("volume_level") is not None:
            self._volume = new_state.attributes["volume_level"]

        if new_state.attributes.get("is_volume_muted") is not None:
            self._muted = new_state.attributes["is_volume_muted"]

        self.async_write_ha_state()

    async def _on_track_finished(self) -> None:
        """Handle when the current track finishes on target."""
        _LOGGER.debug("Track finished, advancing queue")
        if self._queue.has_next:
            await self._advance_to_next()
        else:
            self._state = MediaPlayerState.IDLE
            self.async_write_ha_state()

    def _detect_media_type(self) -> str:
        """Detect the right media_content_type for the target player.

        Each integration has its own accepted media types:
        - cast: "audio/mp3"
        - dlna_dmr: "audio/mpeg"
        - androidtv_remote: "url"
        - others: "music"
        """
        registry = er.async_get(self.hass)
        entry = registry.async_get(self._target_entity_id)
        platform = entry.platform if entry else ""
        media_type_map = {
            "cast": "audio/mp3",
            "dlna_dmr": "audio/mpeg",
            "forked_daapd": "audio/mpeg",
            "squeezebox": "audio/mpeg",
            "androidtv_remote": "url",
        }
        self._needs_proxy = platform in ("dlna_dmr",)
        result = media_type_map.get(platform, "music")
        _LOGGER.debug(
            "Target %s platform=%s → %s (proxy=%s)",
            self._target_entity_id, platform, result, self._needs_proxy,
        )
        return result

    async def _play_on_target(self, url: str) -> None:
        """Send play_media to the target player."""
        play_url = url
        if self._needs_proxy and url.startswith("https://"):
            play_url = generate_proxy_url(self.hass, url)
        _LOGGER.debug(
            "Sending play_media to %s, type=%s, url=%s…",
            self._target_entity_id,
            self._target_media_type,
            play_url[:80],
        )
        self._advancing = True
        try:
            await self.hass.services.async_call(
                "media_player",
                "play_media",
                {
                    "entity_id": self._target_entity_id,
                    "media_content_id": play_url,
                    "media_content_type": self._target_media_type,
                },
                blocking=True,
            )
        finally:
            self._advancing = False

    async def _advance_to_next(self) -> None:
        """Advance to the next track and play it."""
        item = await self._queue.next()
        if item and item.url:
            await self._play_on_target(item.url)
            self._state = MediaPlayerState.PLAYING
            # Pre-fetch next
            self.hass.async_create_task(self._queue.prefetch_next())
            # Send radio feedback
            if self._queue.is_radio and self._queue._radio_station:
                self.hass.async_create_task(
                    self._api.send_radio_started(
                        self._queue._radio_station, item.track_id
                    )
                )
        else:
            self._state = MediaPlayerState.IDLE
        self.async_write_ha_state()

    # ── Media Player Controls ──────────────────────────────────────

    async def async_play_media(
        self,
        media_type: str,
        media_id: str,
        **kwargs: Any,
    ) -> None:
        """Play media from Yandex Music."""
        _LOGGER.debug("play_media: type=%s id=%s", media_type, media_id)

        if media_type in (MEDIA_TYPE_TRACK, MEDIA_TYPE_YANDEX):
            # Single track
            track = await self._api.get_track(media_id)
            if track:
                await self._queue.load_tracks([track])
                item = self._queue.current
                if item and item.url:
                    await self._play_on_target(item.url)
                    self._state = MediaPlayerState.PLAYING

        elif media_type == MEDIA_TYPE_PLAYLIST:
            # Playlist: owner_uid:playlist_id
            parts = media_id.split(":", 1)
            if len(parts) == 2:
                owner_uid, playlist_id = parts
            else:
                owner_uid, playlist_id = self._api.uid, media_id
            tracks = await self._api.get_playlist_tracks(playlist_id, owner_uid)
            if tracks:
                await self._queue.load_tracks(tracks)
                item = self._queue.current
                if item and item.url:
                    await self._play_on_target(item.url)
                    self._state = MediaPlayerState.PLAYING
                    self.hass.async_create_task(self._queue.prefetch_next())

        elif media_type == MEDIA_TYPE_ALBUM:
            tracks = await self._api.get_album_tracks(media_id)
            if tracks:
                await self._queue.load_tracks(tracks)
                item = self._queue.current
                if item and item.url:
                    await self._play_on_target(item.url)
                    self._state = MediaPlayerState.PLAYING
                    self.hass.async_create_task(self._queue.prefetch_next())

        elif media_type == MEDIA_TYPE_ARTIST:
            tracks = await self._api.get_artist_tracks(media_id)
            if tracks:
                await self._queue.load_tracks(tracks)
                item = self._queue.current
                if item and item.url:
                    await self._play_on_target(item.url)
                    self._state = MediaPlayerState.PLAYING
                    self.hass.async_create_task(self._queue.prefetch_next())

        elif media_type == MEDIA_TYPE_RADIO:
            await self._queue.load_radio(media_id)
            item = self._queue.current
            if item and item.url:
                await self._play_on_target(item.url)
                self._state = MediaPlayerState.PLAYING
                if self._queue._radio_station:
                    self.hass.async_create_task(
                        self._api.send_radio_started(
                            self._queue._radio_station, item.track_id
                        )
                    )

        self.async_write_ha_state()

    async def async_media_play(self) -> None:
        """Resume playback."""
        if self._queue.current:
            await self.hass.services.async_call(
                "media_player",
                "media_play",
                {"entity_id": self._target_entity_id},
                blocking=True,
            )
            self._state = MediaPlayerState.PLAYING
            self.async_write_ha_state()

    async def async_media_pause(self) -> None:
        """Pause playback."""
        await self.hass.services.async_call(
            "media_player",
            "media_pause",
            {"entity_id": self._target_entity_id},
            blocking=True,
        )
        self._state = MediaPlayerState.PAUSED
        self.async_write_ha_state()

    async def async_media_stop(self) -> None:
        """Stop playback."""
        await self.hass.services.async_call(
            "media_player",
            "media_stop",
            {"entity_id": self._target_entity_id},
            blocking=True,
        )
        self._state = MediaPlayerState.IDLE
        self.async_write_ha_state()

    async def async_media_next_track(self) -> None:
        """Skip to next track."""
        if self._queue.has_next:
            await self._advance_to_next()

    async def async_media_previous_track(self) -> None:
        """Go back to previous track."""
        item = await self._queue.previous()
        if item and item.url:
            await self._play_on_target(item.url)
            self._state = MediaPlayerState.PLAYING
            self.async_write_ha_state()

    async def async_set_shuffle(self, shuffle: bool) -> None:
        """Set shuffle mode."""
        self._queue.shuffle = shuffle
        self.async_write_ha_state()

    async def async_set_repeat(self, repeat: RepeatMode) -> None:
        """Set repeat mode."""
        if repeat == RepeatMode.ONE:
            self._queue.repeat = REPEAT_ONE
        elif repeat == RepeatMode.ALL:
            self._queue.repeat = REPEAT_ALL
        else:
            self._queue.repeat = REPEAT_OFF
        self.async_write_ha_state()

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume on target player."""
        await self.hass.services.async_call(
            "media_player",
            "volume_set",
            {"entity_id": self._target_entity_id, "volume_level": volume},
            blocking=True,
        )
        self._volume = volume
        self.async_write_ha_state()

    async def async_volume_up(self) -> None:
        """Volume up on target."""
        await self.hass.services.async_call(
            "media_player",
            "volume_up",
            {"entity_id": self._target_entity_id},
            blocking=True,
        )

    async def async_volume_down(self) -> None:
        """Volume down on target."""
        await self.hass.services.async_call(
            "media_player",
            "volume_down",
            {"entity_id": self._target_entity_id},
            blocking=True,
        )

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute/unmute on target."""
        await self.hass.services.async_call(
            "media_player",
            "volume_mute",
            {"entity_id": self._target_entity_id, "is_volume_muted": mute},
            blocking=True,
        )
        self._muted = mute
        self.async_write_ha_state()

    # ── Browse Media ───────────────────────────────────────────────

    async def async_browse_media(
        self,
        media_content_type: str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Browse Yandex Music library.

        When media_content_type is not one of our custom types but
        media_content_id is set, treat it as a search query — this is
        how HA's media browser forwards user search input.
        """
        from .media_browser import async_browse_media

        if (
            media_content_type is not None
            and media_content_id
            and not media_content_type.startswith("ym_")
        ):
            return await async_browse_media(
                self._api, MEDIA_TYPE_SEARCH, media_content_id
            )

        return await async_browse_media(
            self._api, media_content_type, media_content_id
        )
