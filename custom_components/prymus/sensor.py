from __future__ import annotations
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from datetime import timedelta
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util
from .const import DOMAIN
from .helpers import events_between, lesson_status, local
from .parser import WEEKDAYS


async def async_setup_entry(hass, entry, async_add):
    c = hass.data[DOMAIN][entry.entry_id]
    async_add([cls(c, entry) for cls in (GradesCount, LatestGrade, MissedHours, Unexcused, Late,
                                         Remarks, Points, TodayPlan, TomorrowPlan, Announcements,
                                         Now, NextLesson, EventsTomorrow, NextEvent, Unread)])


class Base(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    key = ""

    def __init__(self, c, entry):
        super().__init__(c)
        self._attr_unique_id = f"{entry.entry_id}_{self.key}"
        self._attr_device_info = {"identifiers": {(DOMAIN, entry.entry_id)}, "name": "Prymus e-Dziennik",
                                  "manufacturer": "ZETO Białystok", "model": "Panel rodzica"}

    @property
    def d(self) -> dict:
        return self.coordinator.data or {}


class GradesCount(Base):
    key, _attr_name, _attr_icon = "grades_count", "Liczba ocen", "mdi:school"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return len(self.d.get("grades", []))

    @property
    def extra_state_attributes(self):
        by = {}
        for g in self.d.get("grades", []):
            by.setdefault(g["subject"], []).append(f"{g['category']}: {g['value']}" if g["category"] else g["value"])
        return {"semestr": self.d.get("semester"), "przedmioty": by, "oceny_okresowe": self.d.get("final", {})}


class LatestGrade(Base):
    key, _attr_name, _attr_icon = "latest_grade", "Ostatnia nowa ocena", "mdi:star-circle"

    @property
    def native_value(self):
        h = self.d.get("history", [])
        return f"{h[0]['przedmiot']}: {h[0]['ocena']}"[:255] if h else None

    @property
    def extra_state_attributes(self):
        h = self.d.get("history", [])
        return {**(h[0] if h else {}), "ostatnie": h[:10]}


class _Att(Base):
    _attr_icon, _attr_native_unit_of_measurement = "mdi:account-clock", "h"
    _attr_state_class = SensorStateClass.MEASUREMENT
    field = ""

    @property
    def native_value(self):
        return sum(m[self.field] for m in self.d.get("attendance", []))

    @property
    def extra_state_attributes(self):
        return {"miesiace": {m["miesiac"]: m[self.field] for m in self.d.get("attendance", [])}}


class MissedHours(_Att):
    key, _attr_name, field = "missed", "Godziny opuszczone", "opuszczone"


class Unexcused(_Att):
    key, _attr_name, field, _attr_icon = "unexcused", "Nieusprawiedliwione", "nieusprawiedliwione", "mdi:account-alert"


class Late(_Att):
    key, _attr_name, field, _attr_icon, _attr_native_unit_of_measurement = "late", "Spóźnienia", "spoznienia", "mdi:clock-alert", None


class Remarks(Base):
    key, _attr_name, _attr_icon = "remarks", "Uwagi", "mdi:message-alert"

    @property
    def native_value(self):
        return len(self.d.get("remarks", []))

    @property
    def extra_state_attributes(self):
        r = self.d.get("remarks", [])
        return {"pozytywne": sum(x["status"] == "pozytywna" for x in r),
                "negatywne": sum(x["status"] == "negatywna" for x in r), "lista": r[:10]}


class Points(Base):
    key, _attr_name, _attr_icon = "points", "Punkty zachowania", "mdi:medal"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return sum(p["punkty"] for p in self.d.get("points", []))

    @property
    def extra_state_attributes(self):
        return {"wpisy": self.d.get("points", [])[:10]}


class _Plan(Base):
    _attr_icon, offset = "mdi:timetable", 0

    def _lessons(self):
        day = WEEKDAYS[(dt_util.now().weekday() + self.offset) % 7]
        return day, self.d.get("timetable", {}).get(day, [])

    @property
    def native_value(self):
        return len(self._lessons()[1])

    @property
    def extra_state_attributes(self):
        day, ls = self._lessons()
        return {"dzien": day, "pierwsza": ls[0]["godziny"].split("-")[0].strip() if ls else None,
                "ostatnia_konczy": ls[-1]["godziny"].split("-")[-1].strip() if ls else None, "lekcje": ls}


class TodayPlan(_Plan):
    key, _attr_name = "plan_today", "Lekcje dzisiaj"


class TomorrowPlan(_Plan):
    key, _attr_name, offset = "plan_tomorrow", "Lekcje jutro", 1


class Announcements(Base):
    key, _attr_name, _attr_icon = "announcements", "Ogłoszenia", "mdi:bullhorn"

    @property
    def native_value(self):
        return len(self.d.get("announcements", []))

    @property
    def extra_state_attributes(self):
        a = self.d.get("announcements", [])
        return {"najnowsze": a[0] if a else None, "lista": a[:5]}


class _Clock(Base):
    """Czujnik zależny od godziny – przelicza się co minutę, bez odpytywania serwera."""

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(async_track_time_interval(self.hass, self._tick, timedelta(minutes=1)))

    @callback
    def _tick(self, _now) -> None:
        self.async_write_ha_state()


def _lesson_attrs(l):
    if not l:
        return {}
    return {"przedmiot": l["przedmiot"], "od": local(l["start"]).strftime("%H:%M"), "do": local(l["koniec"]).strftime("%H:%M"),
            "dzien": WEEKDAYS[local(l["start"]).weekday()], "sala": l.get("sala"), "nauczyciel": l.get("nauczyciel")}


class Now(_Clock):
    key, _attr_name, _attr_icon = "now", "Teraz", "mdi:clock-outline"

    @property
    def native_value(self):
        st = lesson_status(self.d)
        return st["teraz"]["przedmiot"][:255] if st["teraz"] else st["stan"]

    @property
    def extra_state_attributes(self):
        st = lesson_status(self.d)
        return {"stan": st["stan"], "lekcja": _lesson_attrs(st["teraz"]), "nastepna": _lesson_attrs(st["nastepna"])}


class NextLesson(_Clock):
    key, _attr_name, _attr_icon = "next_lesson", "Następna lekcja", "mdi:arrow-right-circle"

    @property
    def native_value(self):
        n = lesson_status(self.d)["nastepna"]
        return n["przedmiot"][:255] if n else None

    @property
    def extra_state_attributes(self):
        return _lesson_attrs(lesson_status(self.d)["nastepna"])


class EventsTomorrow(_Clock):
    key, _attr_name, _attr_icon = "events_tomorrow", "Wydarzenia jutro", "mdi:bag-checked"

    def _list(self):
        start = dt_util.start_of_local_day(dt_util.now() + timedelta(days=1))
        return events_between(self.d, start, start + timedelta(days=1))

    @property
    def native_value(self):
        return len(self._list())

    @property
    def extra_state_attributes(self):
        return {"wydarzenia": [{"tytul": e["tytul"], "opis": e["opis"], "godzina": local(e["start"]).strftime("%H:%M")}
                               for e in self._list()]}


class NextEvent(_Clock):
    key, _attr_name, _attr_icon = "next_event", "Najbliższe wydarzenie", "mdi:calendar-arrow-right"

    def _next(self):
        now = dt_util.now()
        evs = [e for e in self.d.get("events", []) if local(e["koniec"]) >= now]
        return evs[0] if evs else None

    @property
    def native_value(self):
        e = self._next()
        return e["tytul"][:255] if e else None

    @property
    def extra_state_attributes(self):
        e = self._next()
        return {"opis": e["opis"], "start": e["start"], "koniec": e["koniec"],
                "za_dni": (local(e["start"]).date() - dt_util.now().date()).days} if e else {}


class Unread(Base):
    key, _attr_name, _attr_icon = "unread", "Nieprzeczytane wiadomości", "mdi:email-alert"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return self.d.get("unread")
