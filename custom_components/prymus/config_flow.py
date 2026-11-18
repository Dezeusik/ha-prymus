from __future__ import annotations
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from .api import PrymusAuthError, PrymusClient
from .const import CONF_EMAIL, CONF_PASSWORD, CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES, DOMAIN


async def _check(hass, email, password):
    c = PrymusClient(async_create_clientsession(hass), email, password)
    await c.login()
    await c.page("oceny")


class PrymusFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input:
            try:
                await _check(self.hass, user_input[CONF_EMAIL], user_input[CONF_PASSWORD])
            except PrymusAuthError:
                errors["base"] = "auth"
            except Exception:  # noqa: BLE001
                errors["base"] = "connect"
            else:
                await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=user_input[CONF_EMAIL], data=user_input)
        schema = vol.Schema({
            vol.Required(CONF_EMAIL): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Optional(CONF_SCAN_MINUTES, default=DEFAULT_SCAN_MINUTES): vol.All(vol.Coerce(int), vol.Range(min=15, max=1440)),
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        errors = {}
        if user_input:
            try:
                await _check(self.hass, entry.data[CONF_EMAIL], user_input[CONF_PASSWORD])
            except PrymusAuthError:
                errors["base"] = "auth"
            except Exception:  # noqa: BLE001
                errors["base"] = "connect"
            else:
                self.hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]})
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")
        return self.async_show_form(step_id="reauth_confirm", data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}), errors=errors)
