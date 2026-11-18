"""Logowanie (login.prymus.net, Laravel) i pobieranie stron panelu rodzica."""
from __future__ import annotations
import re
import aiohttp
from bs4 import BeautifulSoup
from yarl import URL
from .const import LOGIN_URL


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
        async with self._s.get(url, timeout=aiohttp.ClientTimeout(total=45)) as r:
            r.raise_for_status()
            return r.url, await r.text()

    async def login(self) -> None:
        _, html = await self._get(LOGIN_URL)
        tok = BeautifulSoup(html, "html.parser").find("input", {"name": "_token"})
        if not tok:
            raise PrymusError("Brak tokenu CSRF na stronie logowania")
        data = {"_token": tok["value"], "email": self._email, "password": self._password}
        async with self._s.post(LOGIN_URL, data=data, timeout=aiohttp.ClientTimeout(total=45)) as r:
            url, html = r.url, await r.text()
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
            raise PrymusError(f"Nieoczekiwana strona po logowaniu: {url}")
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
