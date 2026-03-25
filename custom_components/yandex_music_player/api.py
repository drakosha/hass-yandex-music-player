"""Yandex Music API wrapper for Home Assistant."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from yandex_music import ClientAsync, Track, Playlist, Album, Artist

from .const import DEFAULT_BITRATE, DEFAULT_CODEC, LIKED_TRACKS_LIMIT

_LOGGER = logging.getLogger(__name__)


class YandexMusicAPI:
    """Wrapper around yandex-music ClientAsync."""

    def __init__(self) -> None:
        self._client: ClientAsync | None = None
        self._uid: int | None = None

    @property
    def client(self) -> ClientAsync:
        assert self._client is not None, "Client not initialized"
        return self._client

    @property
    def uid(self) -> int:
        assert self._uid is not None, "Client not initialized"
        return self._uid

    async def init(self, token: str) -> None:
        """Initialize the client with a token."""
        self._client = await ClientAsync(token).init()
        self._uid = self._client.me.account.uid
        _LOGGER.debug("Yandex Music API initialized for uid=%s", self._uid)

    async def close(self) -> None:
        """Clean up."""
        self._client = None

    # ── Track URL ──────────────────────────────────────────────────

    async def get_track_url(
        self,
        track_id: str | int,
        codec: str = DEFAULT_CODEC,
        bitrate: int = DEFAULT_BITRATE,
    ) -> str | None:
        """Get direct download URL for a track."""
        try:
            dl_info = await self.client.tracks_download_info(
                track_id, get_direct_links=True
            )
            # Filter by codec and pick best bitrate <= requested
            candidates = [
                d for d in dl_info if d.codec == codec
            ]
            if not candidates:
                candidates = dl_info  # fallback to any codec

            # Sort by bitrate descending, pick first <= requested (or highest)
            candidates.sort(key=lambda d: d.bitrate_in_kbps, reverse=True)
            best = None
            for c in candidates:
                if c.bitrate_in_kbps <= bitrate:
                    best = c
                    break
            if best is None and candidates:
                best = candidates[-1]  # lowest available

            if best and best.direct_link:
                _LOGGER.debug(
                    "Got direct_link for track %s (codec=%s, bitrate=%s)",
                    track_id,
                    best.codec,
                    best.bitrate_in_kbps,
                )
                return best.direct_link

            # Fallback: construct URL manually
            if best:
                _LOGGER.debug(
                    "No direct_link, building URL for track %s", track_id
                )
                return await self._build_download_url(best)

            _LOGGER.warning(
                "No download info candidates for track %s", track_id
            )
            return None
        except Exception:
            _LOGGER.exception("Failed to get track URL for %s", track_id)
            return None

    async def _build_download_url(self, dl_info) -> str | None:
        """Build download URL from DownloadInfo object."""
        try:
            await dl_info.get_direct_link_async()
            return dl_info.direct_link
        except Exception:
            _LOGGER.exception("Failed to build direct link")
            return None

    # ── Track info ─────────────────────────────────────────────────

    async def get_track(self, track_id: str | int) -> Track | None:
        """Get track details."""
        try:
            tracks = await self.client.tracks([str(track_id)])
            return tracks[0] if tracks else None
        except Exception:
            _LOGGER.exception("Failed to get track %s", track_id)
            return None

    async def get_tracks(self, track_ids: list[str | int]) -> list[Track]:
        """Get multiple tracks."""
        try:
            return await self.client.tracks([str(t) for t in track_ids])
        except Exception:
            _LOGGER.exception("Failed to get tracks")
            return []

    # ── Library ────────────────────────────────────────────────────

    async def get_liked_tracks(
        self, limit: int = LIKED_TRACKS_LIMIT
    ) -> list[Track]:
        """Get liked tracks (full objects) with batched fetching."""
        try:
            likes = await self.client.users_likes_tracks()
            if not likes:
                return []
            track_ids = [f"{lt.track_id}" for lt in likes[:limit]]
            # Fetch in batches of 100 (API limit)
            all_tracks: list[Track] = []
            for i in range(0, len(track_ids), 100):
                batch = await self.get_tracks(track_ids[i : i + 100])
                all_tracks.extend(batch)
            return all_tracks
        except Exception:
            _LOGGER.exception("Failed to get liked tracks")
            return []

    async def get_playlists(self) -> list[Playlist]:
        """Get user playlists."""
        try:
            return await self.client.users_playlists_list() or []
        except Exception:
            _LOGGER.exception("Failed to get playlists")
            return []

    async def get_playlist_tracks(
        self, playlist_id: int | str, owner_uid: int | str | None = None
    ) -> list[Track]:
        """Get tracks from a playlist."""
        try:
            uid = owner_uid or self.uid
            playlist = await self.client.users_playlists(
                playlist_id, uid
            )
            if not playlist or not playlist.tracks:
                return []
            track_ids = [
                f"{t.track_id}" for t in playlist.tracks
            ]
            return await self.get_tracks(track_ids)
        except Exception:
            _LOGGER.exception("Failed to get playlist tracks")
            return []

    async def get_liked_albums(self) -> list[Album]:
        """Get liked albums (from likes API + extracted from liked tracks)."""
        try:
            album_ids: list[int] = []

            # Try the dedicated likes API first
            likes = await self.client.users_likes_albums()
            if likes:
                for la in likes[:50]:
                    album = getattr(la, "album", None)
                    aid = getattr(album, "id", None) if album else getattr(la, "id", None)
                    if aid:
                        album_ids.append(aid)

            # If empty, extract unique albums from liked tracks
            if not album_ids:
                tracks = await self.get_liked_tracks(limit=100)
                seen = set()
                for track in tracks:
                    for album in track.albums or []:
                        if album.id and album.id not in seen:
                            album_ids.append(album.id)
                            seen.add(album.id)

            if not album_ids:
                return []
            albums = await self.client.albums(album_ids[:50])
            return albums or []
        except Exception:
            _LOGGER.exception("Failed to get liked albums")
            return []

    async def get_album_tracks(self, album_id: int | str) -> list[Track]:
        """Get tracks from an album."""
        try:
            album = await self.client.albums_with_tracks(album_id)
            if not album or not album.volumes:
                return []
            tracks = []
            for volume in album.volumes:
                tracks.extend(volume)
            return tracks
        except Exception:
            _LOGGER.exception("Failed to get album tracks")
            return []

    async def get_liked_artists(self) -> list[Artist]:
        """Get liked artists (from likes API + extracted from liked tracks)."""
        try:
            artists_map: dict[int, Artist] = {}

            # Try the dedicated likes API first
            likes = await self.client.users_likes_artists()
            if likes:
                for la in likes[:50]:
                    artist = getattr(la, "artist", None) or la
                    if hasattr(artist, "name") and artist.name:
                        artists_map[artist.id] = artist

            # If empty, extract unique artists from liked tracks
            if not artists_map:
                tracks = await self.get_liked_tracks(limit=100)
                for track in tracks:
                    for artist in track.artists or []:
                        if artist.id and artist.name and artist.id not in artists_map:
                            artists_map[artist.id] = artist

            return list(artists_map.values())[:50]
        except Exception:
            _LOGGER.exception("Failed to get liked artists")
            return []

    async def get_artist_tracks(self, artist_id: int | str) -> list[Track]:
        """Get popular tracks for an artist."""
        try:
            result = await self.client.artists_tracks(artist_id, page_size=50)
            return result.tracks if result and result.tracks else []
        except Exception:
            _LOGGER.exception("Failed to get artist tracks")
            return []

    # ── Search ─────────────────────────────────────────────────────

    async def search(self, query: str) -> dict[str, Any]:
        """Search Yandex Music."""
        try:
            result = await self.client.search(query)
            return {
                "tracks": result.tracks.results if result.tracks else [],
                "albums": result.albums.results if result.albums else [],
                "artists": result.artists.results if result.artists else [],
                "playlists": result.playlists.results if result.playlists else [],
            }
        except Exception:
            _LOGGER.exception("Failed to search")
            return {"tracks": [], "albums": [], "artists": [], "playlists": []}

    # ── Radio / My Wave ────────────────────────────────────────────

    async def get_radio_stations(self) -> list[dict]:
        """Get available radio stations."""
        try:
            dashboard = await self.client.rotor_stations_dashboard()
            stations = []
            if dashboard and dashboard.stations:
                for station in dashboard.stations:
                    s = station.station
                    stations.append({
                        "id": f"{s.id.type}:{s.id.tag}",
                        "name": s.name,
                        "icon": s.icon.get_url() if s.icon else None,
                    })
            return stations
        except Exception:
            _LOGGER.exception("Failed to get radio stations")
            return []

    async def get_radio_tracks(
        self, station_id: str, last_track_id: str | None = None
    ) -> list[Track]:
        """Get tracks for a radio station. station_id format: 'type:tag'."""
        try:
            parts = station_id.split(":", 1)
            if len(parts) != 2:
                return []
            station_type, station_tag = parts

            # Send feedback about last track if available
            if last_track_id:
                try:
                    await self.client.rotor_station_feedback_track_started(
                        station=f"{station_type}:{station_tag}",
                        track_id=last_track_id,
                    )
                except Exception:
                    pass

            tracks_result = await self.client.rotor_station_tracks(
                station=f"{station_type}:{station_tag}",
            )
            if not tracks_result or not tracks_result.sequence:
                return []

            tracks = []
            for seq_item in tracks_result.sequence:
                if seq_item.track:
                    tracks.append(seq_item.track)
            return tracks
        except Exception:
            _LOGGER.exception("Failed to get radio tracks for %s", station_id)
            return []

    async def send_radio_started(
        self, station_id: str, track_id: str
    ) -> None:
        """Send feedback that a track from radio started playing."""
        try:
            await self.client.rotor_station_feedback_track_started(
                station=station_id, track_id=track_id
            )
        except Exception:
            pass

    async def send_radio_finished(
        self, station_id: str, track_id: str, duration: float
    ) -> None:
        """Send feedback that a track from radio finished playing."""
        try:
            await self.client.rotor_station_feedback_track_finished(
                station=station_id,
                track_id=track_id,
                total_played_seconds=duration,
            )
        except Exception:
            pass


def track_title(track: Track) -> str:
    """Get formatted track title."""
    artists = ", ".join(a.name for a in (track.artists or []) if a.name)
    title = track.title or "Unknown"
    return f"{artists} — {title}" if artists else title


def track_image_url(track: Track, size: str = "200x200") -> str | None:
    """Get track cover image URL."""
    uri = None
    if track.cover_uri:
        uri = track.cover_uri
    elif track.albums:
        for album in track.albums:
            if album.cover_uri:
                uri = album.cover_uri
                break
    if uri:
        return f"https://{uri.replace('%%', size)}"
    return None
