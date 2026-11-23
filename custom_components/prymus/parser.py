"""Parsowanie stron panelu rodzica Prymus (h0X.prymus.net/rodzic/?dz=...).
Bez zależności od Home Assistanta – testowalne samodzielnie."""
from __future__ import annotations
import json
import re
from datetime import date, datetime, time, timedelta
from bs4 import BeautifulSoup, NavigableString, Tag

WEEKDAYS = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _txt(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ") if el is not None else "").replace("\xa0", " ").strip()


def is_login_page(html: str) -> bool:
    s = _soup(html)
    return s.find("input", {"name": "password"}) is not None


def student_name(html: str) -> str | None:
    s = _soup(html)
    for sel in (".user-panel .info", ".dropdown-user", ".user-header"):
        el = s.select_one(sel)
        if el and _txt(el):
            return _txt(el)
    return None


def parse_grades(html: str) -> dict:
    """{'grades': [{subject, category, value}], 'final': {subject: {semestralna, roczna, koncowa}}, 'semester': str}"""
    s = _soup(html)
    table = None
    for t in s.find_all("table"):
        if "Oceny bieżące" in _txt(t.find("thead") or t):
            table = t
            break
    grades, final = [], {}
    if table is None:
        return {"grades": grades, "final": final, "semester": None}
    for tr in (table.find("tbody") or table).find_all("tr", recursive=False):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 2:
            continue
        subject = _txt(tds[0])
        buf = ""
        for node in tds[1].children:
            if isinstance(node, NavigableString):
                buf += str(node)
            elif isinstance(node, Tag) and node.name == "span":
                cat = re.sub(r"\s+", " ", buf.replace("\xa0", " ")).strip(" ;").rstrip(":").strip()
                grades.append({"subject": subject, "category": cat, "value": _txt(node)})
                buf = ""
        f = {k: _txt(tds[i]) for k, i in (("semestralna", 2), ("roczna", 3), ("koncowa", 4)) if i < len(tds)}
        if any(f.values()):
            final[subject] = f
    sel = s.find("select", {"name": "sem"})
    opt = sel.find("option", selected=True) if sel else None
    return {"grades": grades, "final": final, "semester": _txt(opt) if opt else None}


def parse_attendance(html: str) -> list[dict]:
    out = []
    for a in _soup(html).select('td.tabNaglowek a[href*="msz="]'):
        td = a.find_parent("td")
        t = _txt(td)
        def num(label):
            m = re.search(label + r"\s*:\s*(\d+)", t)
            return int(m.group(1)) if m else 0
        out.append({"miesiac": _txt(a), "opuszczone": num("godzin opuszczonych"),
                    "nieusprawiedliwione": num("nieusprawiedliwionych"), "spoznienia": num("liczba spóźnień")})
    return out


def parse_remarks(html: str) -> list[dict]:
    t = _soup(html).find("table", id="myTable")
    out = []
    for tr in (t.find("tbody").find_all("tr") if t and t.find("tbody") else []):
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue
        link = tds[1].find("a")
        rid = re.search(r"id=(\d+)", link["href"]).group(1) if link and link.has_attr("href") and "id=" in link["href"] else None
        span = tds[2].find("span")
        cls = " ".join(span.get("class", [])) if span else ""
        status = "pozytywna" if "pozytyw" in cls else "negatywna" if "negatyw" in cls else "neutralna"
        out.append({"id": rid, "data": _txt(tds[0]), "temat": _txt(tds[1]), "status": status})
    return out


def parse_points(html: str) -> list[dict]:
    t = _soup(html).find("table", id="myTable")
    out = []
    for tr in (t.find("tbody").find_all("tr") if t and t.find("tbody") else []):
        tds = tr.find_all("td")
        if len(tds) >= 3:
            try:
                pts = int(_txt(tds[1]))
            except ValueError:
                pts = 0
            out.append({"data": _txt(tds[0]), "punkty": pts, "opis": _txt(tds[2])})
    return out


def parse_timetable(html: str) -> dict[str, list[dict]]:
    t = _soup(html).find("table", id="pTab")
    plan: dict[str, list[dict]] = {}
    if t is None:
        return plan
    rows = t.find_all("tr")
    days = [_txt(td).lower() for td in rows[0].find_all("td")[1:]] if rows else []
    for tr in rows[1:]:
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 2 or not re.search(r"\d{1,2}:\d{2}", _txt(tds[0])):
            continue
        hours = _txt(tds[0])
        for day, td in zip(days, tds[1:]):
            for div in td.find_all("div", recursive=False):
                b = div.find("b")
                if not b:
                    continue
                lines = [x.strip() for x in div.get_text("\n").replace("\xa0", " ").split("\n") if x.strip()]
                rest = [l for l in lines if l != _txt(b)]
                room = next((l.split(":", 1)[1].strip() for l in rest if l.lower().startswith("sala")), None)
                teacher = next((l for l in rest if not l.lower().startswith("sala")), None)
                plan.setdefault(day, []).append({"godziny": hours, "przedmiot": _txt(b), "nauczyciel": teacher,
                                                 "sala": room, "rodzaj": " ".join(div.get("class", []))})
    return plan


def parse_announcements(html: str) -> list[dict]:
    out = []
    for body in _soup(html).select(".card-body"):
        title = body.select_one(".h4")
        if not title:
            continue
        small = body.find("small")
        date_el = small.select_one(".text-muted") if small else None
        date = _txt(date_el)
        author = _txt(small).replace(date, "").strip() if small else None
        text = _txt(body.select_one(".card-text"))
        out.append({"tytul": _txt(title), "autor": author, "data": date, "tresc": text[:4000]})
    return out


def _iso(v: str | None) -> str | None:
    """'2026-11-16T08:00:00+0100' -> '2026-11-16T08:00:00+01:00' (poprawne ISO dla fromisoformat)."""
    if not v:
        return None
    v = str(v).strip().replace(" ", "T", 1)
    return re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", v)


def parse_events(text: str) -> list[dict]:
    """Kanał kalendarza (POST ?dz=kalendarz, api=1&feed=1) -> lista wydarzeń."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return []
    out = []
    for e in data if isinstance(data, list) else []:
        if not isinstance(e, dict) or not e.get("start"):
            continue
        out.append({"id": str(e.get("id", "")), "tytul": str(e.get("title", "")).strip(),
                    "opis": str(e.get("description") or "").strip(), "start": _iso(e.get("start")),
                    "koniec": _iso(e.get("end")) or _iso(e.get("start")),
                    "klasa": str(e.get("nazwa") or e.get("klasa") or "").strip(" -"),
                    "kolor": e.get("backgroundColor")})
    out.sort(key=lambda e: e["start"])
    return out


def parse_unread(text: str) -> int | None:
    try:
        v = json.loads(text).get("liczbaWiad")
    except (TypeError, ValueError, AttributeError):
        return None
    try:
        return int(v) if str(v).strip() else 0
    except ValueError:
        return None


def lessons_on(timetable: dict, day: date) -> list[dict]:
    """Lekcje w danym dniu z godzinami jako ISO (strefa lokalna doklejana w HA)."""
    name = WEEKDAYS[day.weekday()]
    out = []
    for l in timetable.get(name, []):
        m = re.findall(r"(\d{1,2}):(\d{2})", l["godziny"])
        if len(m) < 2:
            continue
        (h1, m1), (h2, m2) = m[0], m[1]
        out.append({**l, "start": datetime.combine(day, time(int(h1), int(m1))).isoformat(),
                    "koniec": datetime.combine(day, time(int(h2), int(m2))).isoformat()})
    return out


def parse_all(pages: dict[str, str]) -> dict:
    g = parse_grades(pages.get("oceny", ""))
    return {
        "student": student_name(pages.get("oceny", "")),
        "grades": g["grades"], "final": g["final"], "semester": g["semester"],
        "attendance": parse_attendance(pages.get("nieobecn", "")),
        "remarks": parse_remarks(pages.get("inform_ucznia", "")),
        "points": parse_points(pages.get("zdobyte_punkty", "")),
        "timetable": parse_timetable(pages.get("rozkl_ucznia", "")),
        "announcements": parse_announcements(pages.get("ogloszenia", "")),
        "events": parse_events(pages.get("_kalendarz_feed", "")),
        "unread": parse_unread(pages.get("_liczba_wiadomosci", "")),
    }
