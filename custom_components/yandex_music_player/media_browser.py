"""Media browser for Yandex Music Player."""

from __future__ import annotations

import logging

from homeassistant.components.media_player import BrowseMedia, MediaClass

from .api import YandexMusicAPI, track_title, track_image_url
from .const import (
    LIBRARY_ALBUMS,
    LIBRARY_ARTISTS,
    LIBRARY_LIKED,
    LIBRARY_PLAYLISTS,
    LIBRARY_RADIO,
    MEDIA_TYPE_ALBUM,
    MEDIA_TYPE_ARTIST,
    MEDIA_TYPE_LIBRARY,
    MEDIA_TYPE_PLAYLIST,
    MEDIA_TYPE_RADIO,
    MEDIA_TYPE_TRACK,
)

_LOGGER = logging.getLogger(__name__)


async def async_browse_media(
    api: YandexMusicAPI,
    media_content_type: str | None = None,
    media_content_id: str | None = None,
) -> BrowseMedia:
    """Browse Yandex Music library."""
    if media_content_type is None or media_content_id is None:
        return await _build_root(api)

    if media_content_type == MEDIA_TYPE_LIBRARY:
        if media_content_id == LIBRARY_PLAYLISTS:
            return await _build_playlists(api)
        elif media_content_id == LIBRARY_LIKED:
            return await _build_liked_tracks(api)
        elif media_content_id == LIBRARY_ALBUMS:
            return await _build_albums(api)
        elif media_content_id == LIBRARY_ARTISTS:
            return await _build_artists(api)
        elif media_content_id == LIBRARY_RADIO:
            return await _build_radio_stations(api)

    if media_content_type == MEDIA_TYPE_PLAYLIST:
        return await _build_playlist_tracks(api, media_content_id)

    if media_content_type == MEDIA_TYPE_ALBUM:
        return await _build_album_tracks(api, media_content_id)

    if media_content_type == MEDIA_TYPE_ARTIST:
        return await _build_artist_tracks(api, media_content_id)

    return await _build_root(api)


async def _build_root(api: YandexMusicAPI) -> BrowseMedia:
    """Build root browsing menu."""
    children = [
        BrowseMedia(
            title="Мне нравится",
            media_class=MediaClass.DIRECTORY,
            media_content_id=LIBRARY_LIKED,
            media_content_type=MEDIA_TYPE_LIBRARY,
            can_play=True,  # Play all liked tracks
            can_expand=True,
            thumbnail=None,
        ),
        BrowseMedia(
            title="Плейлисты",
            media_class=MediaClass.DIRECTORY,
            media_content_id=LIBRARY_PLAYLISTS,
            media_content_type=MEDIA_TYPE_LIBRARY,
            can_play=False,
            can_expand=True,
            thumbnail=None,
        ),
        BrowseMedia(
            title="Альбомы",
            media_class=MediaClass.DIRECTORY,
            media_content_id=LIBRARY_ALBUMS,
            media_content_type=MEDIA_TYPE_LIBRARY,
            can_play=False,
            can_expand=True,
            thumbnail=None,
        ),
        BrowseMedia(
            title="Исполнители",
            media_class=MediaClass.DIRECTORY,
            media_content_id=LIBRARY_ARTISTS,
            media_content_type=MEDIA_TYPE_LIBRARY,
            can_play=False,
            can_expand=True,
            thumbnail=None,
        ),
        BrowseMedia(
            title="Радио",
            media_class=MediaClass.DIRECTORY,
            media_content_id=LIBRARY_RADIO,
            media_content_type=MEDIA_TYPE_LIBRARY,
            can_play=False,
            can_expand=True,
            thumbnail=None,
        ),
    ]
    return BrowseMedia(
        title="Яндекс Музыка",
        media_class=MediaClass.DIRECTORY,
        media_content_id="",
        media_content_type=MEDIA_TYPE_LIBRARY,
        can_play=False,
        can_expand=True,
        children=children,
    )


async def _build_playlists(api: YandexMusicAPI) -> BrowseMedia:
    """Build playlist listing."""
    playlists = await api.get_playlists()
    children = []
    for pl in playlists:
        cover = None
        if hasattr(pl, "cover") and pl.cover:
            if hasattr(pl.cover, "uri") and pl.cover.uri:
                cover = f"https://{pl.cover.uri.replace('%%', '200x200')}"
            elif hasattr(pl.cover, "items_uri") and pl.cover.items_uri:
                uri = pl.cover.items_uri[0]
                cover = f"https://{uri.replace('%%', '200x200')}"

        children.append(
            BrowseMedia(
                title=pl.title or "Без названия",
                media_class=MediaClass.PLAYLIST,
                media_content_id=f"{pl.uid}:{pl.kind}",
                media_content_type=MEDIA_TYPE_PLAYLIST,
                can_play=True,
                can_expand=True,
                thumbnail=cover,
            )
        )

    return BrowseMedia(
        title="Плейлисты",
        media_class=MediaClass.DIRECTORY,
        media_content_id=LIBRARY_PLAYLISTS,
        media_content_type=MEDIA_TYPE_LIBRARY,
        can_play=False,
        can_expand=True,
        children=children,
    )


async def _build_liked_tracks(api: YandexMusicAPI) -> BrowseMedia:
    """Build liked tracks listing."""
    tracks = await api.get_liked_tracks()
    children = _tracks_to_children(tracks)

    return BrowseMedia(
        title="Мне нравится",
        media_class=MediaClass.PLAYLIST,
        media_content_id=LIBRARY_LIKED,
        media_content_type=MEDIA_TYPE_LIBRARY,
        can_play=True,
        can_expand=True,
        children=children,
    )


async def _build_albums(api: YandexMusicAPI) -> BrowseMedia:
    """Build liked albums listing."""
    albums = await api.get_liked_albums()
    children = []
    for album in albums:
        cover = None
        if hasattr(album, "cover_uri") and album.cover_uri:
            cover = f"https://{album.cover_uri.replace('%%', '200x200')}"

        artists = ""
        if hasattr(album, "artists") and album.artists:
            artists = ", ".join(a.name for a in album.artists if a.name)

        title = album.title or "Без названия"
        if artists:
            title = f"{artists} — {title}"

        children.append(
            BrowseMedia(
                title=title,
                media_class=MediaClass.ALBUM,
                media_content_id=str(album.id),
                media_content_type=MEDIA_TYPE_ALBUM,
                can_play=True,
                can_expand=True,
                thumbnail=cover,
            )
        )

    return BrowseMedia(
        title="Альбомы",
        media_class=MediaClass.DIRECTORY,
        media_content_id=LIBRARY_ALBUMS,
        media_content_type=MEDIA_TYPE_LIBRARY,
        can_play=False,
        can_expand=True,
        children=children,
    )


async def _build_artists(api: YandexMusicAPI) -> BrowseMedia:
    """Build liked artists listing."""
    artists = await api.get_liked_artists()
    children = []
    for artist in artists:
        cover = None
        if hasattr(artist, "cover") and artist.cover:
            if hasattr(artist.cover, "uri") and artist.cover.uri:
                cover = f"https://{artist.cover.uri.replace('%%', '200x200')}"

        children.append(
            BrowseMedia(
                title=artist.name or "Неизвестный",
                media_class=MediaClass.ARTIST,
                media_content_id=str(artist.id),
                media_content_type=MEDIA_TYPE_ARTIST,
                can_play=True,
                can_expand=True,
                thumbnail=cover,
            )
        )

    return BrowseMedia(
        title="Исполнители",
        media_class=MediaClass.DIRECTORY,
        media_content_id=LIBRARY_ARTISTS,
        media_content_type=MEDIA_TYPE_LIBRARY,
        can_play=False,
        can_expand=True,
        children=children,
    )


async def _build_radio_stations(api: YandexMusicAPI) -> BrowseMedia:
    """Build radio station listing."""
    stations = await api.get_radio_stations()

    # Always add "My Wave" first
    children = [
        BrowseMedia(
            title="Моя волна",
            media_class=MediaClass.CHANNEL,
            media_content_id="user:onyourwave",
            media_content_type=MEDIA_TYPE_RADIO,
            can_play=True,
            can_expand=False,
            thumbnail=None,
        ),
    ]

    for station in stations:
        children.append(
            BrowseMedia(
                title=station["name"],
                media_class=MediaClass.CHANNEL,
                media_content_id=station["id"],
                media_content_type=MEDIA_TYPE_RADIO,
                can_play=True,
                can_expand=False,
                thumbnail=station.get("icon"),
            )
        )

    return BrowseMedia(
        title="Радио",
        media_class=MediaClass.DIRECTORY,
        media_content_id=LIBRARY_RADIO,
        media_content_type=MEDIA_TYPE_LIBRARY,
        can_play=False,
        can_expand=True,
        children=children,
    )


async def _build_playlist_tracks(
    api: YandexMusicAPI, playlist_id: str
) -> BrowseMedia:
    """Build track listing for a playlist."""
    parts = playlist_id.split(":", 1)
    if len(parts) == 2:
        owner_uid, pl_id = parts
    else:
        owner_uid, pl_id = api.uid, playlist_id

    tracks = await api.get_playlist_tracks(pl_id, owner_uid)
    children = _tracks_to_children(tracks)

    return BrowseMedia(
        title="Плейлист",
        media_class=MediaClass.PLAYLIST,
        media_content_id=playlist_id,
        media_content_type=MEDIA_TYPE_PLAYLIST,
        can_play=True,
        can_expand=True,
        children=children,
    )


async def _build_album_tracks(
    api: YandexMusicAPI, album_id: str
) -> BrowseMedia:
    """Build track listing for an album."""
    tracks = await api.get_album_tracks(album_id)
    children = _tracks_to_children(tracks)

    return BrowseMedia(
        title="Альбом",
        media_class=MediaClass.ALBUM,
        media_content_id=album_id,
        media_content_type=MEDIA_TYPE_ALBUM,
        can_play=True,
        can_expand=True,
        children=children,
    )


async def _build_artist_tracks(
    api: YandexMusicAPI, artist_id: str
) -> BrowseMedia:
    """Build track listing for an artist."""
    tracks = await api.get_artist_tracks(artist_id)
    children = _tracks_to_children(tracks)

    return BrowseMedia(
        title="Исполнитель",
        media_class=MediaClass.ARTIST,
        media_content_id=artist_id,
        media_content_type=MEDIA_TYPE_ARTIST,
        can_play=True,
        can_expand=True,
        children=children,
    )


def _tracks_to_children(tracks: list) -> list[BrowseMedia]:
    """Convert track list to BrowseMedia children."""
    children = []
    for track in tracks:
        children.append(
            BrowseMedia(
                title=track_title(track),
                media_class=MediaClass.TRACK,
                media_content_id=str(track.id),
                media_content_type=MEDIA_TYPE_TRACK,
                can_play=True,
                can_expand=False,
                thumbnail=track_image_url(track),
            )
        )
    return children
