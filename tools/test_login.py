#!/usr/bin/env python3
"""Diagnostyka logowania do Prymusa – bez Home Assistanta, tylko biblioteka standardowa.

Uruchomienie (hasło wpisujesz lokalnie, nie trafia nigdzie poza serwer Prymusa):
    curl -sL https://raw.githubusercontent.com/Dezeusik/ha-prymus/main/tools/test_login.py | python3 - twoj@email

Wypisuje każdy krok przekierowań (bez kodów, tokenów i wartości ciasteczek), a na końcu
co pokazuje strona wyboru ucznia, jeśli logowanie w nią utknie.
"""
import getpass
import http.client
import re
import ssl
import sys
import time
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")
BASE_HDR = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Upgrade-Insecure-Requests": "1",
}
SECRET = {"code", "state", "token", "enc", "_token", "password"}
LOGIN = "https://login.prymus.net/login"


def show(url):
    p = urlsplit(url)
    q = "&".join(f"{k}={'…' if k.lower() in SECRET else v[:40]}" for k, v in parse_qsl(p.query, keep_blank_values=True))
    return f"{p.netloc}{p.path}" + (f"?{q}" if q else "")


class Jar:
    def __init__(self):
        self.c = {}

    def update(self, url, headers):
        host, names = urlsplit(url).hostname, []
        for raw in headers:
            parts = [x.strip() for x in raw.split(";")]
            if "=" not in parts[0]:
                continue
            name, value = (s.strip() for s in parts[0].split("=", 1))
            attrs = {}
            for a in parts[1:]:
                k, _, v = a.partition("=")
                attrs[k.strip().lower()] = v.strip()
            dom = attrs.get("domain", "").lstrip(".").lower()
            host_only, dom = not dom, dom or host
            path = attrs.get("path") or "/"
            dead = False
            if "max-age" in attrs:
                dead = attrs["max-age"].lstrip("-").isdigit() and int(attrs["max-age"]) <= 0
            elif "expires" in attrs:
                try:
                    dead = parsedate_to_datetime(attrs["expires"]).timestamp() < time.time()
                except (TypeError, ValueError):
                    pass
            key = (name, dom, path)
            if dead:
                self.c.pop(key, None)
            else:
                self.c[key] = (value, host_only)
            names.append(name + ("(usunięte)" if dead else "") + (f"@{dom}" if not host_only else "") + f"[{path}]")
        return names

    def header(self, url):
        p = urlsplit(url)
        host, upath, out = p.hostname, p.path or "/", {}
        for (name, dom, path), (value, host_only) in sorted(self.c.items(), key=lambda kv: len(kv[0][2])):
            ok = host == dom if host_only else (host == dom or host.endswith("." + dom))
            if ok and upath.startswith(path):
                out[name] = value
        return "; ".join(f"{k}={v}" for k, v in out.items())


class Client:
    def __init__(self, patient=True):
        self.jar, self.patient, self.ctx = Jar(), patient, ssl.create_default_context()

    def one(self, method, url, body=None, extra=None):
        p = urlsplit(url)
        conn = http.client.HTTPSConnection(p.hostname, p.port or 443, context=self.ctx, timeout=45)
        path = p.path or "/"
        if p.query:
            path += "?" + p.query
        hdr = {**BASE_HDR, **(extra or {})}
        ck = self.jar.header(url)
        if ck:
            hdr["Cookie"] = ck
        conn.request(method, path, body=body, headers=hdr)
        r = conn.getresponse()
        data = r.read()
        setc = self.jar.update(url, r.headers.get_all("Set-Cookie") or [])
        conn.close()
        return r.status, r.headers.get("Location"), data.decode("utf-8", "replace"), setc

    def go(self, method, url, body=None, extra=None, max_hops=40, max_same=10):
        t0, seen = time.monotonic(), {}
        for _ in range(max_hops):
            status, loc, html, setc = self.one(method, url, body, extra)
            nxt = urljoin(url, loc) if loc and 300 <= status < 400 else None
            print(f"  {time.monotonic() - t0:5.1f}s {method:4} {show(url)} -> {status}"
                  + (f" -> {show(nxt)}" if nxt else "") + (f"   ustawia: {', '.join(setc)}" if setc else ""))
            if not nxt:
                return url, status, html
            seen[nxt] = seen.get(nxt, 0) + 1
            if seen[nxt] > max_same:
                print(f"  !! pętla na {show(nxt)}; wysyłane ciasteczka: "
                      f"{', '.join(k.split('=')[0] for k in self.jar.header(nxt).split('; ') if k)}")
                return nxt, 0, ""
            if seen[nxt] > 1 and self.patient:
                time.sleep(min(0.3 * seen[nxt], 2.0))
            if status in (301, 302, 303):
                method, body = "GET", None
                extra = {k: v for k, v in (extra or {}).items() if k not in ("Content-Type", "Origin")}
            url = nxt
        print("  !! za dużo przekierowań")
        return url, 0, ""


def describe(html):
    title = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    print("     tytuł:", unescape(title.group(1).strip()) if title else "-")
    for f in re.findall(r"<form\b.*?</form>", html, re.S | re.I)[:5]:
        action = re.search(r'action="([^"]*)"', f)
        fields = re.findall(r'<(?:input|select|button)[^>]*name="([^"]+)"', f)
        opts = [unescape(re.sub(r"<[^>]+>", "", o)).strip()[:30] for o in re.findall(r"<option[^>]*>(.*?)</option>", f, re.S)]
        print(f"     formularz -> {show(urljoin('https://h04.prymus.net/rodzic/', action.group(1))) if action else '(ta sama strona)'}"
              f" pola: {', '.join(fields)}" + (f" opcje: {opts[:6]}" if opts else ""))
    links = sorted(set(re.findall(r'href="(\?dz=[^"#]+)"', html)))
    if links:
        print("     linki ?dz=:", ", ".join(show("https://x/" + unescape(l)).split("x/", 1)[1] for l in links[:15]))
    text = re.sub(r"\s+", " ", unescape(re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", html, flags=re.S)))
    print("     tekst:", text.strip()[:400])


def main():
    if len(sys.argv) < 2:
        sys.exit("Użycie: python3 test_login.py twoj@email")
    email, pwd = sys.argv[1], getpass.getpass("Hasło do Prymusa (nie wyświetla się): ")
    c = Client()
    print("\n1) Strona logowania")
    _, _, html = c.go("GET", LOGIN)
    tok = re.search(r'name="_token"\s+value="([^"]+)"', html) or re.search(r'value="([^"]+)"\s+name="_token"', html)
    if not tok:
        sys.exit("Brak tokenu CSRF na stronie logowania.")
    print("\n2) Wysłanie formularza i przejście do panelu")
    body = urlencode({"_token": tok.group(1), "email": email, "password": pwd})
    url, status, html = c.go("POST", LOGIN, body, {"Content-Type": "application/x-www-form-urlencoded",
                                                  "Origin": "https://login.prymus.net", "Referer": LOGIN})
    if status == 200 and "/rodzic/" in urlsplit(url).path and 'name="password"' not in html:
        print("\nOK – panel rodzica otwarty:", show(url))
        describe(html)
        return
    if "login.prymus.net" in url and 'name="password"' in html:
        sys.exit("\nLogowanie odrzucone – zły e-mail/hasło albo konto nieaktywne.")
    for delay in (3, 8):
        print(f"\n3) Ponowne wejście do panelu po {delay} s (sesja SSO zostaje)")
        time.sleep(delay)
        url, status, html = c.go("GET", "https://login.prymus.net/home")
        if status == 200 and "/rodzic/" in urlsplit(url).path:
            print("\nOK – panel otwarty za drugim podejściem:", show(url))
            describe(html)
            return
    print("\n4) Co pokazuje strona wyboru ucznia (bez podążania za przekierowaniem):")
    for target in ("https://h04.prymus.net/rodzic/?dz=wybor_ucznia", "https://h04.prymus.net/rodzic/"):
        host_url = target.replace("h04.prymus.net", urlsplit(url).netloc or "h04.prymus.net")
        status, loc, html, setc = c.one("GET", host_url)
        print(f"  {show(host_url)} -> {status}" + (f" -> {show(urljoin(host_url, loc))}" if loc else ""))
        describe(html)
    print("\nNie udało się wejść do panelu. Skopiuj cały wynik i wklej go Claude'owi.")


if __name__ == "__main__":
    try:
        main()
    except ssl.SSLError as e:
        sys.exit(f"Błąd SSL ({e}). Na Macu z Pythonem z python.org uruchom najpierw "
                 "'Install Certificates.command' z folderu Aplikacje/Python 3.x.")
