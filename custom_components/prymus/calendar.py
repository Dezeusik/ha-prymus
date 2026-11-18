from __future__ import annotations
from datetime import datetime, timedelta
from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from .const import DOMAIN
from .helpers import events_between, lessons, local


async def async_setup_entry(hass, entry, async_add):
    c = hass.data[DOMAIN][entry.entry_id]
    async_add([SchoolEvents(c, entry), Timetable(c, entry)])


class _Cal(CoordinatorEntity, CalendarEntity):
    _attr_has_entity_name = True
    key = ""

    def __init__(self, c, entry):
        super().__init__(c)
        self._attr_unique_id = f"{entry.entry_id}_{self.key}"
        self._attr_device_info = {"identifiers": {(DOMAIN, entry.entry_id)}}

    def _events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        raise NotImplementedError

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        evs = [e for e in self._events(now - timedelta(days=1), now + timedelta(days=60)) if e.end > now]
        return min(evs, key=lambda e: e.start) if evs else None

    async def async_get_events(self, hass, start_date: datetime, end_date: datetime) -> list[CalendarEvent]:
        return self._events(start_date, end_date)


class SchoolEvents(_Cal):
    key, _attr_name, _attr_icon = "cal_events", "Wydarzenia szkolne", "mdi:calendar-star"

    def _events(self, start, end):
        return [CalendarEvent(start=local(e["start"]), end=max(local(e["koniec"]), local(e["start"]) + timedelta(minutes=1)),
                              summary=e["tytul"], description=e["opis"] or None, uid=f"prymus-{e['id']}")
                for e in events_between(self.coordinator.data, start, end)]


class Timetable(_Cal):
    """Plan lekcji z bieżącego tygodnia, powtarzany na kolejne tygodnie (bez zastępstw i dni wolnych)."""
    key, _attr_name, _attr_icon = "cal_timetable", "Plan lekcji", "mdi:timetable"

    def _events(self, start, end):
        out, day = [], start.date()
        last = min(end.date(), start.date() + timedelta(days=62))
        while day <= last:
            for l in lessons(self.coordinator.data, day):
                s, e = local(l["start"]), local(l["koniec"])
                if s < end and e > start:
                    out.append(CalendarEvent(start=s, end=e, summary=l["przedmiot"],
                                             description=l.get("nauczyciel"), location=f"sala {l['sala']}" if l.get("sala") else None))
            day += timedelta(days=1)
        return out
