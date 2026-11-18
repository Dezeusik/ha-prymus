#!/usr/bin/env python3
"""Test poza HA: loguje się i wypisuje podsumowanie sparsowanych danych.
pip install beautifulsoup4 ; python3 test_login.py twoj@email"""
import getpass, http.cookiejar, json, re, sys, urllib.parse, urllib.request
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), "..", "custom_components", "prymus"))
import parser as P  # noqa: E402

email = sys.argv[1]; pwd = getpass.getpass("Hasło: ")
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
get = lambda u, d=None: (lambda r: (r.geturl(), r.read().decode("utf-8", "replace")))(op.open(u, d, timeout=45))
_, h = get("https://login.prymus.net/login")
tok = re.search(r'name="_token"\s+value="([^"]+)"', h) or re.search(r'value="([^"]+)"\s+name="_token"', h)
url, h = get("https://login.prymus.net/login", urllib.parse.urlencode({"_token": tok.group(1), "email": email, "password": pwd}).encode())
print("Po logowaniu:", url)
if "/rodzic/" not in url:
    sys.exit("Nie trafiłem do panelu rodzica – sprawdź dane albo wklej Claude'owi powyższy adres.")
base = url.split("/rodzic/")[0] + "/rodzic/"
pages = {p: get(base + "?dz=" + p)[1] for p in ("oceny", "nieobecn", "inform_ucznia", "zdobyte_punkty", "rozkl_ucznia", "ogloszenia")}
d = P.parse_all(pages)
print(json.dumps({"semestr": d["semester"], "ocen": len(d["grades"]), "przyklad_oceny": d["grades"][:3],
                  "frekwencja": d["attendance"], "uwag": len(d["remarks"]), "punkty": sum(p["punkty"] for p in d["points"]),
                  "dni_planu": {k: len(v) for k, v in d["timetable"].items()}, "ogloszen": len(d["announcements"])},
                 ensure_ascii=False, indent=1))
