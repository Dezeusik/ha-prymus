"""Logowanie (login.prymus.net, Laravel) i pobieranie stron panelu rodzica."""
from __future__ import annotations
import logging
import re
import aiohttp
from bs4 import BeautifulSoup
from yarl import URL
from .const import LOGIN_URL

_LOGGER = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ha-prymus/0.2.2; +https://github.com/Dezeusik/ha-prymus)",
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

    async def _req(self, method: str, url, data=None, headers=None) -> tuple[URL, int, str, list[str]]:
        """Request z ręcznym śledzeniem przekierowań (do 25, bez przerabiania adresów).
        Zwraca (końcowy URL, status, html, opis kroków)."""
        url = URL(str(url), encoded=isinstance(url, URL) and url.is_absolute())
        hops: list[str] = []
        seen: dict[str, int] = {}
        for _ in range(25):
            async with self._s.request(method, url, data=data, headers={**HEADERS, **(headers or {})},
                                       allow_redirects=False, timeout=aiohttp.ClientTimeout(total=45)) as r:
                status = r.status
                set_ck = ",".join(sorted({c for c in r.cookies})) or "-"
                loc = r.headers.get("Location")
                html = "" if loc and 300 <= status < 400 else await r.text(errors="replace")
            hops.append(f"{method} {_short(url)} -> {status} [cookies: {set_ck}]")
            if not (loc and 300 <= status < 400):
                return url, status, html, hops
            nxt = url.join(URL(loc, encoded=True))
            key = str(nxt)
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 2:
                sent = ",".join(sorted(c.key for c in self._s.cookie_jar.filter_cookies(nxt).values())) or "-"
                hops.append(f"PĘTLA na {_short(nxt)}; ciasteczka wysyłane tam: {sent}")
                _LOGGER.warning("Prymus: pętla przekierowań:\n  %s", "\n  ".join(hops))
                raise PrymusError("Pętla przekierowań: " + " | ".join(hops[-6:]))
            if status in (301, 302, 303):
                method, data = "GET", None
            url = nxt
        _LOGGER.warning("Prymus: za dużo przekierowań:\n  %s", "\n  ".join(hops))
        raise PrymusError("Za dużo przekierowań: " + " | ".join(hops[-6:]))

    async def _get(self, url) -> tuple[URL, str]:
        url, status, html, hops = await self._req("GET", url)
        _LOGGER.debug("Prymus GET:\n  %s", "\n  ".join(hops))
        if status >= 400:
            raise PrymusError(f"HTTP {status} z {_short(url)}")
        return url, html

    async def login(self) -> None:
        _, html = await self._get(LOGIN_URL)
        if "/rodzic/" in _.path:  # już zalogowani (ciasteczka z poprzedniej sesji)
            self.base = _.with_path("/rodzic/").with_query({})
            return
        tok = BeautifulSoup(html, "html.parser").find("input", {"name": "_token"})
        if not tok:
            raise PrymusError("Brak tokenu CSRF na stronie logowania")
        data = {"_token": tok["value"], "email": self._email, "password": self._password}
        hdr = {"Origin": "https://login.prymus.net", "Referer": LOGIN_URL,
               "Content-Type": "application/x-www-form-urlencoded"}
        url, status, html, hops = await self._req("POST", URL(LOGIN_URL), data=data, headers=hdr)
        _LOGGER.debug("Prymus logowanie:\n  %s", "\n  ".join(hops))
        if status == 419:
            raise PrymusError("HTTP 419 (CSRF) – serwer nie przyjął ciasteczka sesji")
        if status >= 400:
            raise PrymusError(f"HTTP {status} po logowaniu ({_short(url)})")
        for _i in range(4):  # ewentualne przekierowania JS / meta refresh
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
                              f"{title.group(1).strip()[:60] if title else '-'}) | " + " | ".join(hops[-5:]))
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
