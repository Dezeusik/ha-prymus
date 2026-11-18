from __future__ import annotations
from collections import Counter
from datetime import timedelta
import logging
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from .api import PrymusAuthError, PrymusClient
from .const import DOMAIN, EVENT_NEW_GRADE, EVENT_NEW_REMARK, PAGES
from .parser import parse_all

_LOGGER = logging.getLogger(__name__)


def _gkey(g: dict) -> str:
    return f"{g['subject']}|{g['category']}|{g['value']}"


class PrymusCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, client: PrymusClient, entry_id: str, minutes: int) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=timedelta(minutes=minutes))
        self.client = client
        self._store = Store(hass, 1, f"{DOMAIN}_{entry_id}")
        self._state: dict | None = None

    async def _async_update_data(self):
        if self._state is None:
            self._state = await self._store.async_load() or {}
        try:
            pages = {p: await self.client.page(p) for p in PAGES}
        except PrymusAuthError as e:
            raise ConfigEntryAuthFailed(str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise UpdateFailed(str(e)) from e
        data = await self.hass.async_add_executor_job(parse_all, pages)

        first_run = "grades" not in self._state
        now = dt_util.now().isoformat(timespec="minutes")
        # nowe oceny: różnica multizbiorów (ta sama ocena z tej samej kategorii może wystąpić 2x)
        old = Counter(self._state.get("grades", []))
        cur = Counter(_gkey(g) for g in data["grades"])
        new_keys = list((cur - old).elements())
        history = self._state.get("history", [])
        if not first_run:
            for k in new_keys:
                subj, cat, val = k.split("|", 2)
                ev = {"przedmiot": subj, "kategoria": cat, "ocena": val, "wykryto": now}
                history.insert(0, ev)
                self.hass.bus.async_fire(EVENT_NEW_GRADE, ev)
            old_r = set(self._state.get("remarks", []))
            for r in data["remarks"]:
                if r["id"] and r["id"] not in old_r:
                    self.hass.bus.async_fire(EVENT_NEW_REMARK, r)
        self._state = {"grades": list(cur.elements()), "history": history[:30],
                       "remarks": [r["id"] for r in data["remarks"] if r["id"]]}
        await self._store.async_save(self._state)
        data["history"] = self._state["history"]
        return data
