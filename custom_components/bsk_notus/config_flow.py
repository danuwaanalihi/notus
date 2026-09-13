"""Config flow for BSK NOTUS."""

from collections.abc import Mapping
import logging
from typing import Any, override

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    BSKNotusAuthError,
    BSKNotusClient,
    BSKNotusConnectionError,
    BSKNotusError,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_CREDENTIAL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): vol.All(str, vol.Length(min=1)),
        vol.Required(CONF_PASSWORD): vol.All(str, vol.Length(min=1)),
    }
)

_PASSWORD_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): vol.All(str, vol.Length(min=1)),
    }
)


class BSKNotusConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BSK NOTUS."""

    VERSION = 1

    @override
    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = str(user_input[CONF_USERNAME]).strip()
            password = str(user_input[CONF_PASSWORD])

            error = await self._async_validate_credentials(username, password)
            if error is None:
                await self.async_set_unique_id(username.casefold())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"BSK NOTUS ({username})",
                    data={CONF_USERNAME: username, CONF_PASSWORD: password},
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=_CREDENTIAL_SCHEMA,
            errors=errors,
        )

    @override
    async def async_step_reauth(
        self,
        entry_data: Mapping[str, Any],
    ) -> ConfigFlowResult:
        """Start reauthentication for an existing config entry."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Confirm updated BSK Connect credentials."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        username = str(entry.data[CONF_USERNAME])

        if user_input is not None:
            password = str(user_input[CONF_PASSWORD])
            error = await self._async_validate_credentials(username, password)
            if error is None:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_PASSWORD: password},
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_PASSWORD_SCHEMA,
            errors=errors,
            description_placeholders={"username": username},
        )

    async def _async_validate_credentials(
        self,
        username: str,
        password: str,
    ) -> str | None:
        """Validate login and require at least one supported NOTUS device."""
        client = BSKNotusClient(
            async_get_clientsession(self.hass),
            username,
            password,
        )
        try:
            devices = await client.async_list_notus_devices()
        except BSKNotusAuthError:
            return "invalid_auth"
        except BSKNotusConnectionError:
            return "cannot_connect"
        except BSKNotusError:
            _LOGGER.exception("Unexpected BSK Connect API response during setup")
            return "unknown"
        except Exception:
            _LOGGER.exception("Unexpected error during BSK NOTUS setup")
            return "unknown"

        if not devices:
            return "no_notus"
        return None
