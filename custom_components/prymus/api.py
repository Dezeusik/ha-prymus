"""Logowanie (login.prymus.net, Laravel) i pobieranie stron panelu rodzica."""
from __future__ import annotations
import asyncio
import logging
import re
import time
from email.utils import parsedate_to_datetime
import aiohttp
from bs4 import BeautifulSoup
from yarl import URL
from .const import LOGIN_URL

_LOGGER = logging.getLogger(__name__)
# Nagłówki jak w zwykłym Chrome: serwer panelu rozróżnia przeglądarki po stronie serwera.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
}
MAX_HOPS = 40          # przeglądarka: 20 na jedną nawigację
MAX_SAME_URL = 10      # ile razy wolno trafić na ten sam adres (serwer bywa "w trakcie")
_SECRET_PARAMS = {"code", "state", "token", "enc", "password", "_token", "client_secret"}


def _show(url) -> str:
    """Adres do logu: host, ścieżka i parametry, z ukrytymi wartościami poufnymi."""
    u = URL(str(url))
    q = "&".join(f"{k}={'…' if k.lower() in _SECRET_PARAMS else v[:40]}" for k, v in u.query.items())
    return f"{u.host}{u.path}" + (f"?{q}" if q else "")


def _short(url) -> str:
    u = URL(str(url))
    return f"{u.host}{u.path}"


class PrymusAuthError(Exception):
    """Złe dane logowania albo konto nieaktywne."""


class PrymusError(Exception):
    pass


class _Jar:
    """Minimalny, tolerancyjny słoik ciasteczek. aiohttp (http.cookies.SimpleCookie) po cichu
    odrzuca niektóre nagłówki Set-Cookie serwerów Prymusa, co kończy się pętlą przekierowań."""

    def __init__(self) -> None:
        self._c: dict[tuple[str, str, str], dict] = {}

    def update(self, url: URL, raw_headers: list[str]) -> list[str]:
        names = []
        host = (url.host or "").lower()
        for raw in raw_headers:
            parts = [p.strip() for p in raw.split(";")]
            if "=" not in parts[0]:
                continue
            name, value = parts[0].split("=", 1)
            name, value = name.strip(), value.strip()
            attrs: dict[str, str] = {}
            for a in parts[1:]:
                k, _, v = a.partition("=")
                attrs[k.strip().lower()] = v.strip()
            domain = attrs.get("domain", "").lstrip(".").lower()
            host_only = not domain
            domain = domain or host
            path = attrs.get("path") or "/"
            expired = False
            if "max-age" in attrs:
                try:
                    expired = int(attrs["max-age"]) <= 0
                except ValueError:
                    pass
            elif "expires" in attrs:
                try:
                    expired = parsedate_to_datetime(attrs["expires"]).timestamp() < time.time()
                except (TypeError, ValueError):
                    pass
            key = (name, domain, path)
            if expired:
                self._c.pop(key, None)
            else:
                self._c[key] = {"value": value, "host_only": host_only}
            names.append(name + ("(-)" if expired else "") + ("" if host_only else f"@{domain}") +
                          "{" + ",".join(sorted(k for k in attrs if k not in ("expires", "max-age", "path", "domain"))) + "}")
        return names

    def header(self, url: URL) -> str:
        host, upath, out = (url.host or "").lower(), url.path or "/", {}
        for (name, domain, path), c in sorted(self._c.items(), key=lambda kv: len(kv[0][2])):
            ok = host == domain if c["host_only"] else (host == domain or host.endswith("." + domain))
            if ok and upath.startswith(path):
                out[name] = c["value"]
        return "; ".join(f"{k}={v}" for k, v in out.items())

    def value(self, url: URL, name: str) -> str | None:
        for part in self.header(url).split("; "):
            k, _, v = part.partition("=")
            if k == name:
                return v
        return None

    def names_for(self, url: URL) -> str:
        return ",".join(k.split("=")[0] for k in self.header(url).split("; ") if k) or "-"


_JS_REDIR = re.compile(r"""(?:window\.|document\.)?location(?:\.href)?\s*=\s*["']([^"']+)["']""")
_META_REDIR = re.compile(r"""<meta[^>]+http-equiv=["']?refresh["']?[^>]*url=([^"'>]+)""", re.I)


class PrymusClient:
    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        self._s, self._email, self._password = session, email, password
        self._jar = _Jar()
        self.base: URL | None = None  # np. https://h0X.prymus.net/rodzic/

    async def _req(self, method: str, url, data=None, headers=None) -> tuple[URL, int, str, list[str]]:
        """Request z ręcznym śledzeniem przekierowań (do 25, bez przerabiania adresów).
        Zwraca (końcowy URL, status, html, opis kroków)."""
        url = URL(str(url), encoded=isinstance(url, URL) and url.is_absolute())
        hops: list[str] = []
        seen: dict[str, int] = {}
        referer = (headers or {}).get("Referer")
        t0 = time.monotonic()
        for _ in range(MAX_HOPS):
            hdr = {**HEADERS, **(headers or {})}
            hdr["Sec-Fetch-Site"] = "none" if referer is None else (
                "same-origin" if URL(referer).host == url.host else "same-site")
            if referer and "Referer" not in hdr:
                hdr["Referer"] = referer
            ck = self._jar.header(url)
            if ck:
                hdr["Cookie"] = ck
            async with self._s.request(method, url, data=data, headers=hdr,
                                       allow_redirects=False, timeout=aiohttp.ClientTimeout(total=45)) as r:
                status = r.status
                set_ck = " ".join(self._jar.update(r.url, r.headers.getall("Set-Cookie", []))) or "-"
                loc = r.headers.get("Location")
                html = "" if loc and 300 <= status < 400 else await r.text(errors="replace")
            hops.append(f"{time.monotonic() - t0:5.1f}s {method} {_show(url)} -> {status} [set: {set_ck}]"
                        + (f" -> {_show(url.join(URL(loc, encoded=True)))}" if loc and 300 <= status < 400 else ""))
            if not (loc and 300 <= status < 400):
                return url, status, html, hops
            nxt = url.join(URL(loc, encoded=True))
            key = str(nxt)
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 1:
                await asyncio.sleep(min(0.3 * seen[key], 2.0))  # daj serwerowi chwilę, jak przeglądarka
            if seen[key] > MAX_SAME_URL:
                sent = self._jar.names_for(nxt)
                hops.append(f"PĘTLA na {_show(nxt)}; ciasteczka wysyłane tam: {sent}")
                _LOGGER.warning("Prymus: pętla przekierowań:\n  %s", "\n  ".join(hops))
                raise PrymusError("Pętla przekierowań: " + " | ".join(hops[-5:]))
            if status in (301, 302, 303):
                method, data = "GET", None
                headers = {k: v for k, v in (headers or {}).items() if k not in ("Content-Type", "Origin")}
            url = nxt
        _LOGGER.warning("Prymus: za dużo przekierowań:\n  %s", "\n  ".join(hops))
        raise PrymusError("Za dużo przekierowań: " + " | ".join(hops[-5:]))

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
        try:
            url, status, html, hops = await self._req("POST", URL(LOGIN_URL), data=data, headers=hdr)
        except PrymusError as first:
            if "/rodzic" not in str(first):
                raise
            # sesja SSO już jest – po chwili wejdź do panelu jeszcze raz, od zera
            last = first
            for delay in (3, 8):
                await asyncio.sleep(delay)
                try:
                    url, status, html, hops = await self._req("GET", URL("https://login.prymus.net/home"))
                    break
                except PrymusError as e:
                    last = e
            else:
                raise last
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

    async def calendar_feed(self, start, end, tz: str = "+01:00") -> str:
        """Wydarzenia kalendarza szkolnego – to samo zapytanie, które wysyła strona (FullCalendar)."""
        for attempt in (0, 1):
            if self.base is None:
                await self.login()
            page = self.base.with_query({"dz": "kalendarz"})
            await self._get(page)  # odświeża XSRF-TOKEN dla /rodzic/
            body = (f"api=1&feed=1&filtr=-2&start={start.isoformat()}T00:00:00{tz}"
                    f"&end={end.isoformat()}T00:00:00{tz}").replace("+", "%2B").replace(":", "%3A")
            hdr = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "Accept": "application/json, */*",
                   "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Referer": str(page),
                   "X-XSRF-TOKEN": self._jar.value(page, "XSRF-TOKEN") or ""}
            url, status, text, _hops = await self._req("POST", page, data=body, headers=hdr)
            if status == 200 and text.lstrip().startswith("["):
                return text
            if "/rodzic/" in url.path and status == 200:
                return "[]"
            self.base = None
        _LOGGER.warning("Prymus: nie udało się pobrać kalendarza (HTTP %s)", status)
        return "[]"

    async def unread(self) -> str:
        if self.base is None:
            await self.login()
        url = self.base.with_path("/rodzic/AJAX.php").with_query({"dz": "liczba_wiadomosci"})
        try:
            _u, status, text, _h = await self._req("GET", url, headers={"Accept": "application/json, */*",
                                                                       "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors"})
        except PrymusError:
            return ""
        return text if status == 200 else ""

    async def page(self, dz: str, **params) -> str:
        for attempt in (0, 1):
            if self.base is None:
                await self.login()
            url, html = await self._get(self.base.with_query({"dz": dz, **params}))
            if "/rodzic/" in url.path and 'name="password"' not in html:
                return html
            self.base = None  # sesja wygasła – logujemy ponownie
        raise PrymusAuthError("Sesja wygasła i ponowne logowanie się nie udało")
