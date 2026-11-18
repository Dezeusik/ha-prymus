from __future__ import annotations
from datetime import timedelta
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from .const import DOMAIN
from .helpers import lesson_status, local


async def async_setup_entry(hass, entry, async_add):
    c = hass.data[DOMAIN][entry.entry_id]
    async_add([LessonsToday(c, entry), AtSchool(c, entry)])


class _Base(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True
    key = ""

    def __init__(self, c, entry):
        super().__init__(c)
        self._attr_unique_id = f"{entry.entry_id}_{self.key}"
        self._attr_device_info = {"identifiers": {(DOMAIN, entry.entry_id)}}

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(async_track_time_interval(self.hass, self._tick, timedelta(minutes=1)))

    @callback
    def _tick(self, _now) -> None:
        self.async_write_ha_state()


class LessonsToday(_Base):
    key, _attr_name, _attr_icon = "lessons_today", "Lekcje dzisiaj", "mdi:school-outline"

    @property
    def is_on(self):
        return bool(lesson_status(self.coordinator.data)["dzisiaj"])


class AtSchool(_Base):
    """Od początku pierwszej do końca ostatniej lekcji (wg planu)."""
    key, _attr_name, _attr_icon = "at_school", "W szkole teraz", "mdi:bag-personal"

    @property
    def is_on(self):
        today = lesson_status(self.coordinator.data)["dzisiaj"]
        now = dt_util.now()
        return bool(today) and local(today[0]["start"]) <= now < local(today[-1]["koniec"])
