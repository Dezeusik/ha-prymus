"""Logowanie (login.prymus.net, Laravel) i pobieranie stron panelu rodzica."""
from __future__ import annotations
import logging
import re
import aiohttp
from bs4 import BeautifulSoup
from yarl import URL
from .const import LOGIN_URL

_LOGGER = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ha-prymus/0.2.1; +https://github.com/Dezeusik/ha-prymus)",
           "Accept": "text/html,application/xhtml+xml", "Accept-Language": "pl-PL,pl;q=0.9"}


def _short(url) -> str:
    u = URL(str(url))
    return f"{u.host}{u.path}"


class PrymusAuthError(Exception):
    """Złe dane logowania albo konto nieaktywne."""


class PrymusError(Exception):
    pass


_JS_REDIR = re.compile(r"""(?:window\.|document\.)?location(?:\.href)?\s*=\s*["']([^"']+)["']""")
_META_REDIR = re.compile(r"""<meta[^>]+http-equiv=["']?refresh["']?[^>]*url=([^"'>]+)""", re.I)


class PrymusClient:
    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        self._s, self._email, self._password = session, email, password
        self.base: URL | None = None  # np. https://h0X.prymus.net/rodzic/

    async def _get(self, url) -> tuple[URL, str]:
        async with self._s.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=45)) as r:
            html = await r.text(errors="replace")
            _LOGGER.debug("GET %s -> %s %s (%d B)", _short(url), r.status, _short(r.url), len(html))
            if r.status >= 400:
                raise PrymusError(f"HTTP {r.status} z {_short(r.url)}")
            return r.url, html

    async def login(self) -> None:
        _, html = await self._get(LOGIN_URL)
        tok = BeautifulSoup(html, "html.parser").find("input", {"name": "_token"})
        if not tok:
            raise PrymusError("Brak tokenu CSRF na stronie logowania")
        data = {"_token": tok["value"], "email": self._email, "password": self._password}
        hdr = {**HEADERS, "Origin": "https://login.prymus.net", "Referer": LOGIN_URL}
        async with self._s.post(LOGIN_URL, data=data, headers=hdr, timeout=aiohttp.ClientTimeout(total=45)) as r:
            url, html, status = r.url, await r.text(errors="replace"), r.status
            hops = " -> ".join(_short(h.url) for h in r.history) or "brak"
        _LOGGER.debug("POST login -> %s %s, przekierowania: %s", status, _short(url), hops)
        if status == 419:
            raise PrymusError("HTTP 419 (CSRF) – serwer nie przyjął ciasteczka sesji")
        if status >= 400:
            raise PrymusError(f"HTTP {status} po logowaniu ({_short(url)})")
        for _ in range(4):  # ewentualne przekierowania JS / meta refresh między domenami
            if "/rodzic/" in url.path:
                break
            m = _META_REDIR.search(html) or _JS_REDIR.search(html)
            if not m:
                break
            url, html = await self._get(url.join(URL(m.group(1).strip())))
        if "/rodzic/" not in url.path:
            if url.host and url.host.startswith("login.") and 'name="password"' in html:
                raise PrymusAuthError("Logowanie odrzucone")
            title = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
            raise PrymusError(f"Po logowaniu trafiłem na {_short(url)} (HTTP {status}, tytuł: "
                              f"{title.group(1).strip()[:60] if title else '-'}, przekierowania: {hops})")
        self.base = url.with_path("/rodzic/").with_query({})

    async def page(self, dz: str, **params) -> str:
        for attempt in (0, 1):
            if self.base is None:
                await self.login()
            url, html = await self._get(self.base.with_query({"dz": dz, **params}))
            if "/rodzic/" in url.path and 'name="password"' not in html:
                return html
            self.base = None  # sesja wygasła – logujemy ponownie
        raise PrymusAuthError("Sesja wygasła i ponowne logowanie się nie udało")
