"""Config flow for Yandex Music Player."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_TARGET_PLAYER,
    CONF_YANDEX_STATION_ENTRY,
    DOMAIN,
    YANDEX_STATION_DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _get_yandex_station_entries(hass: HomeAssistant) -> dict[str, str]:
    """Get available YandexStation config entries."""
    entries = {}
    for entry in hass.config_entries.async_entries(YANDEX_STATION_DOMAIN):
        entries[entry.entry_id] = entry.title or entry.unique_id or entry.entry_id
    return entries


def _get_media_players(hass: HomeAssistant) -> dict[str, str]:
    """Get available media_player entities."""
    players = {}
    registry = er.async_get(hass)

    # Get all media_player states
    for state in hass.states.async_all("media_player"):
        entity_id = state.entity_id
        # Skip Yandex stations — we want external players
        entry = registry.async_get(entity_id)
        if entry and entry.platform == YANDEX_STATION_DOMAIN:
            continue
        # Skip our own entities
        if entry and entry.platform == DOMAIN:
            continue

        friendly_name = state.attributes.get("friendly_name", entity_id)
        players[entity_id] = friendly_name

    return players


class YandexMusicPlayerConfigFlow(
    config_entries.ConfigFlow, domain=DOMAIN
):
    """Config flow for Yandex Music Player."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle user-initiated setup."""
        errors = {}

        # Check if YandexStation is installed
        ys_entries = _get_yandex_station_entries(self.hass)
        if not ys_entries:
            return self.async_abort(reason="yandex_station_not_found")

        # Get available media players
        players = _get_media_players(self.hass)
        if not players:
            return self.async_abort(reason="no_media_players")

        if user_input is not None:
            target_player = user_input[CONF_TARGET_PLAYER]
            ys_entry = user_input[CONF_YANDEX_STATION_ENTRY]

            # Validate that selected entry exists
            if ys_entry not in ys_entries:
                errors["base"] = "invalid_yandex_station"
            elif target_player not in players:
                errors["base"] = "invalid_player"
            else:
                # Check for duplicate
                await self.async_set_unique_id(
                    f"ym_{target_player}"
                )
                self._abort_if_unique_id_configured()

                player_name = players[target_player]
                return self.async_create_entry(
                    title=f"YM → {player_name}",
                    data={
                        CONF_TARGET_PLAYER: target_player,
                        CONF_YANDEX_STATION_ENTRY: ys_entry,
                    },
                )

        # Default to first YandexStation entry if only one
        default_ys = list(ys_entries.keys())[0] if len(ys_entries) == 1 else vol.UNDEFINED

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_TARGET_PLAYER,
                ): vol.In(players),
                vol.Required(
                    CONF_YANDEX_STATION_ENTRY,
                    default=default_ys,
                ): vol.In(ys_entries),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle reconfiguration to change target player."""
        errors = {}
        entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )

        players = _get_media_players(self.hass)
        if not players:
            return self.async_abort(reason="no_media_players")

        if user_input is not None:
            new_target = user_input[CONF_TARGET_PLAYER]
            if new_target not in players:
                errors["base"] = "invalid_player"
            else:
                new_data = {**entry.data, CONF_TARGET_PLAYER: new_target}
                self.hass.config_entries.async_update_entry(
                    entry, data=new_data
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_TARGET_PLAYER,
                    default=entry.data.get(CONF_TARGET_PLAYER),
                ): vol.In(players),
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
        )
