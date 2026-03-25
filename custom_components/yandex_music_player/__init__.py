"""Yandex Music Player integration for Home Assistant.

Plays Yandex Music on any media_player entity with queue management,
library browsing, and radio support. Uses YandexStation for authentication.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import YandexMusicAPI
from .const import CONF_YANDEX_STATION_ENTRY, DOMAIN, YANDEX_STATION_DOMAIN
from .proxy import async_register_proxy

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.MEDIA_PLAYER]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration (YAML not supported, only config flow)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Yandex Music Player from a config entry."""
    ys_entry_id = entry.data[CONF_YANDEX_STATION_ENTRY]

    # Get the YandexStation Quasar object for auth
    ys_data = hass.data.get(YANDEX_STATION_DOMAIN)
    if not ys_data:
        raise ConfigEntryNotReady(
            "YandexStation integration not loaded yet"
        )

    # Find the quasar object - try entry_id first, then unique_id
    quasar = None
    ys_entry = None
    for e in hass.config_entries.async_entries(YANDEX_STATION_DOMAIN):
        if e.entry_id == ys_entry_id:
            ys_entry = e
            break

    if ys_entry is None:
        raise ConfigEntryNotReady(
            f"YandexStation entry {ys_entry_id} not found"
        )

    # YandexStation stores quasar in hass.data[DOMAIN][unique_id]
    quasar = ys_data.get(ys_entry.unique_id)
    if quasar is None:
        # Fallback: try entry_id
        quasar = ys_data.get(ys_entry_id)
    if quasar is None:
        # Last resort: iterate values
        for key, val in ys_data.items():
            if hasattr(val, "session"):
                quasar = val
                break

    if quasar is None:
        raise ConfigEntryNotReady(
            "Could not find YandexStation quasar object"
        )

    # Extract the music token from YandexStation session
    token = await _get_music_token(hass, quasar)
    if not token:
        raise ConfigEntryNotReady(
            "Could not obtain Yandex Music token from YandexStation"
        )

    # Initialize the API
    api = YandexMusicAPI()
    try:
        await api.init(token)
    except Exception as exc:
        raise ConfigEntryNotReady(
            f"Failed to initialize Yandex Music API: {exc}"
        ) from exc

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "quasar": quasar,
    }

    async_register_proxy(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info(
        "Yandex Music Player set up for uid=%s, target=%s",
        api.uid,
        entry.data.get("target_player"),
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    )
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if data and "api" in data:
            await data["api"].close()
    return unload_ok


async def _get_music_token(hass: HomeAssistant, quasar) -> str | None:
    """Extract or obtain a Yandex Music token from YandexStation's quasar.

    YandexStation's session stores auth data that we can use to get
    a music token. The approach depends on the YandexStation version:
    - Some versions expose music_token directly
    - Others need to exchange the x_token for a music token
    """
    session = getattr(quasar, "session", None)
    if session is None:
        _LOGGER.error("Quasar object has no session attribute")
        return None

    # Try 1: Direct music_token attribute
    if hasattr(session, "music_token"):
        token = session.music_token
        if token:
            _LOGGER.debug("Got music_token directly from session")
            return token

    # Try 2: x_token → exchange for music token via OAuth
    x_token = getattr(session, "x_token", None)
    if x_token:
        token = await _exchange_x_token_for_music(hass, session, x_token)
        if token:
            return token

    # Try 3: Try to get token from cookies/session data
    # The session may have a method to get tokens
    for attr_name in ("token", "_token", "oauth_token", "_x_token"):
        token = getattr(session, attr_name, None)
        if token and isinstance(token, str):
            _LOGGER.debug("Got token from session.%s", attr_name)
            return token

    # Try 4: Use the session's cookies to get a music token
    if hasattr(session, "get") or hasattr(session, "session"):
        token = await _get_token_via_session(hass, session)
        if token:
            return token

    _LOGGER.error(
        "Could not extract music token. "
        "Available session attributes: %s",
        [a for a in dir(session) if not a.startswith("__")],
    )
    return None


async def _exchange_x_token_for_music(
    hass: HomeAssistant, session, x_token: str
) -> str | None:
    """Exchange x_token for a Yandex Music OAuth token."""
    try:
        # Standard Yandex OAuth token exchange
        data = {
            "grant_type": "x-token",
            "client_id": "23cabbbdc6cd418abb4b39c32c41195d",
            "client_secret": "53bc75238f0c4d08a118e51fe9203300",
            "access_token": x_token,
        }
        http = async_get_clientsession(hass)
        async with http.post(
            "https://oauth.yandex.ru/token", data=data
        ) as resp:
            if resp.status == 200:
                result = await resp.json()
                token = result.get("access_token")
                if token:
                    _LOGGER.debug("Got music token via x_token exchange")
                    return token
            else:
                text = await resp.text()
                _LOGGER.warning(
                    "x_token exchange failed: %s %s",
                    resp.status,
                    text[:200],
                )
    except Exception:
        _LOGGER.exception("Failed to exchange x_token")
    return None


async def _get_token_via_session(
    hass: HomeAssistant, session
) -> str | None:
    """Try to get a music token using the session's HTTP capabilities."""
    try:
        # YandexStation session may have a `get` method with auth
        if hasattr(session, "get"):
            resp = await session.get(
                "https://oauth.yandex.ru/token",
                params={
                    "grant_type": "sessionid",
                    "client_id": "23cabbbdc6cd418abb4b39c32c41195d",
                    "client_secret": "53bc75238f0c4d08a118e51fe9203300",
                    "host": "oauth.yandex.ru",
                },
            )
            if hasattr(resp, "json"):
                data = await resp.json()
            else:
                import json
                data = json.loads(await resp.text())

            token = data.get("access_token")
            if token:
                _LOGGER.debug("Got music token via session request")
                return token
    except Exception:
        _LOGGER.debug("Failed to get token via session", exc_info=True)
    return None
