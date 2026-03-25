"""HTTP proxy for streaming HTTPS audio to DLNA renderers.

Old DLNA devices (like NAD D7050) cannot handle HTTPS URLs.
This module registers an HA HTTP view that proxies the audio stream
so DLNA renderers can access it over plain HTTP.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

import aiohttp
from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# In-memory store: token -> {url, expires}
_proxy_urls: dict[str, dict[str, Any]] = {}

PROXY_PATH = "/api/yandex_music_player/proxy"
TOKEN_TTL = 1800  # 30 min


def generate_proxy_url(hass: HomeAssistant, original_url: str) -> str:
    """Generate a proxied HTTP URL for the given HTTPS URL."""
    token = hashlib.sha256(
        f"{original_url}{time.time()}".encode()
    ).hexdigest()[:24]
    _proxy_urls[token] = {
        "url": original_url,
        "expires": time.time() + TOKEN_TTL,
    }
    # Clean up expired tokens
    now = time.time()
    expired = [k for k, v in _proxy_urls.items() if v["expires"] < now]
    for k in expired:
        _proxy_urls.pop(k, None)

    base_url = hass.config.internal_url or hass.config.external_url
    if not base_url:
        # Fallback: construct from HA config
        base_url = f"http://{hass.config.api.host}:{hass.config.api.port}"
    # Ensure HTTP (not HTTPS) for DLNA compatibility
    base_url = base_url.replace("https://", "http://")
    return f"{base_url}{PROXY_PATH}/{token}.mp3"


class YandexMusicProxyView(HomeAssistantView):
    """Proxy view that streams audio from HTTPS to HTTP."""

    url = PROXY_PATH + "/{token}.mp3"
    name = "api:yandex_music_player:proxy"
    requires_auth = False  # DLNA renderers can't send HA tokens

    async def get(self, request: web.Request, token: str) -> web.StreamResponse:
        """Stream the proxied audio."""
        entry = _proxy_urls.get(token)
        if not entry or entry["expires"] < time.time():
            return web.Response(status=404, text="Not found or expired")

        original_url = entry["url"]
        _LOGGER.debug("Proxying audio: %s…", original_url[:80])

        hass: HomeAssistant = request.app["hass"]
        session = async_get_clientsession(hass)

        try:
            async with session.get(original_url) as upstream:
                if upstream.status != 200:
                    return web.Response(
                        status=502,
                        text=f"Upstream returned {upstream.status}",
                    )

                response = web.StreamResponse(
                    status=200,
                    headers={
                        "Content-Type": "audio/mpeg",
                        "Accept-Ranges": "none",
                        "Cache-Control": "no-cache",
                    },
                )
                if upstream.content_length:
                    response.content_length = upstream.content_length

                await response.prepare(request)

                async for chunk in upstream.content.iter_chunked(65536):
                    await response.write(chunk)

                await response.write_eof()
                return response
        except Exception:
            _LOGGER.exception("Proxy stream error")
            return web.Response(status=502, text="Proxy error")


def async_register_proxy(hass: HomeAssistant) -> None:
    """Register the proxy view if not already registered."""
    key = f"{DOMAIN}_proxy_registered"
    if hass.data.get(key):
        return
    hass.http.register_view(YandexMusicProxyView)
    hass.data[key] = True
    _LOGGER.debug("Registered audio proxy at %s", PROXY_PATH)
