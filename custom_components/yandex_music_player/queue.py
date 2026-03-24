"""Queue manager for Yandex Music Player."""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Any

from yandex_music import Track

from .api import YandexMusicAPI, track_title, track_image_url
from .const import REPEAT_ALL, REPEAT_OFF, REPEAT_ONE

_LOGGER = logging.getLogger(__name__)


@dataclass
class QueueItem:
    """Single item in the playback queue."""

    track: Track
    url: str | None = None

    @property
    def track_id(self) -> str:
        return str(self.track.id)

    @property
    def title(self) -> str:
        return track_title(self.track)

    @property
    def duration(self) -> float | None:
        if self.track.duration_ms:
            return self.track.duration_ms / 1000
        return None

    @property
    def image_url(self) -> str | None:
        return track_image_url(self.track)


class PlayQueue:
    """Manages the playback queue with repeat, shuffle, and radio support."""

    def __init__(self, api: YandexMusicAPI) -> None:
        self._api = api
        self._items: list[QueueItem] = []
        self._position: int = -1
        self._repeat: str = REPEAT_OFF
        self._shuffle: bool = False
        self._shuffle_order: list[int] = []
        self._radio_station: str | None = None
        self._url_cache: dict[str, str] = {}

    @property
    def items(self) -> list[QueueItem]:
        return self._items

    @property
    def position(self) -> int:
        return self._position

    @property
    def current(self) -> QueueItem | None:
        if 0 <= self._position < len(self._items):
            idx = self._get_actual_index(self._position)
            return self._items[idx]
        return None

    @property
    def repeat(self) -> str:
        return self._repeat

    @repeat.setter
    def repeat(self, value: str) -> None:
        self._repeat = value

    @property
    def shuffle(self) -> bool:
        return self._shuffle

    @shuffle.setter
    def shuffle(self, value: bool) -> None:
        self._shuffle = value
        if value:
            self._rebuild_shuffle_order()
        else:
            self._shuffle_order = []

    @property
    def is_radio(self) -> bool:
        return self._radio_station is not None

    @property
    def has_next(self) -> bool:
        if self._radio_station:
            return True
        if self._repeat in (REPEAT_ONE, REPEAT_ALL):
            return len(self._items) > 0
        return self._position < len(self._items) - 1

    @property
    def has_previous(self) -> bool:
        return self._position > 0

    def _get_actual_index(self, pos: int) -> int:
        """Map logical position to actual index (respects shuffle)."""
        if self._shuffle and self._shuffle_order:
            if 0 <= pos < len(self._shuffle_order):
                return self._shuffle_order[pos]
        return pos

    def _rebuild_shuffle_order(self) -> None:
        """Rebuild shuffle order, keeping current track first."""
        order = list(range(len(self._items)))
        if self._position >= 0 and self._position < len(order):
            current_actual = self._get_actual_index(self._position)
            order.remove(current_actual)
            random.shuffle(order)
            order.insert(0, current_actual)
            self._shuffle_order = order
            self._position = 0
        else:
            random.shuffle(order)
            self._shuffle_order = order

    # ── Queue manipulation ─────────────────────────────────────────

    async def load_tracks(self, tracks: list[Track]) -> None:
        """Load a list of tracks into the queue."""
        self._radio_station = None
        self._items = [QueueItem(track=t) for t in tracks]
        self._position = 0 if self._items else -1
        if self._shuffle:
            self._rebuild_shuffle_order()
        # Pre-fetch URL for first track
        if self.current:
            await self._ensure_url(self.current)

    async def load_radio(self, station_id: str) -> None:
        """Start radio mode."""
        self._radio_station = station_id
        self._items = []
        self._position = -1
        self._shuffle = False
        self._shuffle_order = []
        await self._fetch_radio_tracks()
        if self._items:
            self._position = 0
            await self._ensure_url(self.current)

    def clear(self) -> None:
        """Clear the queue."""
        self._items = []
        self._position = -1
        self._radio_station = None
        self._shuffle_order = []

    # ── Navigation ─────────────────────────────────────────────────

    async def next(self) -> QueueItem | None:
        """Advance to the next track. Returns new current or None."""
        if not self._items:
            return None

        if self._repeat == REPEAT_ONE:
            # Re-play same track
            item = self.current
            if item:
                await self._ensure_url(item)
            return item

        next_pos = self._position + 1

        if next_pos >= len(self._items):
            if self._radio_station:
                # Fetch more radio tracks
                last_track_id = self.current.track_id if self.current else None
                if last_track_id:
                    await self._api.send_radio_finished(
                        self._radio_station, last_track_id, 0
                    )
                await self._fetch_radio_tracks()
                if self._items:
                    self._position = 0
                    await self._ensure_url(self.current)
                    return self.current
                return None
            elif self._repeat == REPEAT_ALL:
                next_pos = 0
                if self._shuffle:
                    self._rebuild_shuffle_order()
            else:
                return None

        self._position = next_pos
        item = self.current
        if item:
            await self._ensure_url(item)
        return item

    async def previous(self) -> QueueItem | None:
        """Go to previous track."""
        if not self._items or self._position <= 0:
            # Restart current track
            item = self.current
            if item:
                await self._ensure_url(item)
            return item

        self._position -= 1
        item = self.current
        if item:
            await self._ensure_url(item)
        return item

    async def jump_to(self, index: int) -> QueueItem | None:
        """Jump to specific position in queue."""
        if 0 <= index < len(self._items):
            self._position = index
            item = self.current
            if item:
                await self._ensure_url(item)
            return item
        return None

    # ── URL management ─────────────────────────────────────────────

    async def _ensure_url(self, item: QueueItem) -> None:
        """Ensure the track has a valid URL."""
        if not item.url:
            url = await self._api.get_track_url(item.track_id)
            if url:
                item.url = url
            else:
                _LOGGER.warning(
                    "Failed to get URL for track %s (%s)",
                    item.track_id,
                    item.title,
                )

    async def prefetch_next(self) -> None:
        """Pre-fetch URL for the next track."""
        if self._position + 1 < len(self._items):
            next_idx = self._get_actual_index(self._position + 1)
            if 0 <= next_idx < len(self._items):
                await self._ensure_url(self._items[next_idx])

    # ── Radio ──────────────────────────────────────────────────────

    async def _fetch_radio_tracks(self) -> None:
        """Fetch more tracks for radio mode."""
        if not self._radio_station:
            return
        last_id = self.current.track_id if self.current else None
        tracks = await self._api.get_radio_tracks(
            self._radio_station, last_id
        )
        if tracks:
            self._items = [QueueItem(track=t) for t in tracks]
            self._position = 0
            _LOGGER.debug(
                "Fetched %d radio tracks for %s",
                len(tracks),
                self._radio_station,
            )
