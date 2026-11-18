"""Wspólne obliczenia czasu dla czujników i kalendarzy (strefa czasowa HA)."""
from __future__ import annotations
from datetime import date, datetime, timedelta
from homeassistant.util import dt as dt_util
from .parser import lessons_on


def local(iso: str) -> datetime:
    d = datetime.fromisoformat(iso)
    return d if d.tzinfo else d.replace(tzinfo=dt_util.get_default_time_zone())


def lessons(data: dict, day: date) -> list[dict]:
    return lessons_on((data or {}).get("timetable", {}), day)


def lesson_status(data: dict, now: datetime | None = None) -> dict:
    """Co się dzieje teraz: lekcja / przerwa / przed lekcjami / po lekcjach / wolne + następna lekcja."""
    now = now or dt_util.now()
    today = lessons(data, now.date())
    cur = next((l for l in today if local(l["start"]) <= now < local(l["koniec"])), None)
    nxt = next((l for l in today if local(l["start"]) > now), None)
    if nxt is None:  # szukaj w kolejnych dniach (do tygodnia)
        for i in range(1, 8):
            ls = lessons(data, now.date() + timedelta(days=i))
            if ls:
                nxt = ls[0]
                break
    if not today:
        state = "wolne"
    elif cur:
        state = "lekcja"
    elif now < local(today[0]["start"]):
        state = "przed lekcjami"
    elif now >= local(today[-1]["koniec"]):
        state = "po lekcjach"
    else:
        state = "przerwa"
    return {"stan": state, "teraz": cur, "nastepna": nxt, "dzisiaj": today}


def events_between(data: dict, start: datetime, end: datetime) -> list[dict]:
    return [e for e in (data or {}).get("events", []) if local(e["start"]) < end and local(e["koniec"]) >= start]
