# Prymus e-Dziennik → Home Assistant

Nieoficjalna integracja dla panelu rodzica Prymus (ZETO Białystok). Loguje się tak samo jak
przeglądarka: e-mailem i hasłem na `login.prymus.net`. Potem czyta strony panelu `h0X.prymus.net/rodzic/`.
Nie trzeba przechwytywać tokenów z telefonu.

> Projekt prywatny, niezwiązany z ZETO Białystok ani z producentem dziennika Prymus.
> Używaj go tylko z własnym kontem rodzica.

## Instalacja przez HACS
HACS → menu ⋮ → *Custom repositories* → wklej adres tego repozytorium, kategoria **Integration**,
następnie zainstaluj „Prymus e-Dziennik” i zrestartuj HA.

## Instalacja ręczna
1. Skopiuj `custom_components/prymus` do `/config/custom_components/` i zrestartuj HA.
2. Ustawienia → Urządzenia i usługi → Dodaj integrację → **Prymus**.
3. Wpisz e-mail i hasło do dziennika. Domyślnie dane odświeżają się co 60 min, minimum to 15.

Możesz najpierw sprawdzić logowanie poza HA: `pip install beautifulsoup4 && python3 tools/test_login.py twoj@email`.

## Encje
**Czujniki**
| Encja | Stan | Atrybuty |
|---|---|---|
| Liczba ocen | ile ocen bieżących | oceny wg przedmiotu, oceny okresowe, semestr |
| Ostatnia nowa ocena | „Przedmiot: ocena” | kategoria, kiedy wykryto, 10 ostatnich |
| Godziny opuszczone / Nieusprawiedliwione / Spóźnienia | suma w semestrze | podział na miesiące |
| Uwagi | liczba | pozytywne, negatywne, lista |
| Punkty zachowania | suma | wpisy |
| Lekcje dzisiaj / jutro | liczba lekcji | pierwsza, koniec ostatniej, lista z salami |
| Teraz | przedmiot trwającej lekcji albo `przerwa` / `przed lekcjami` / `po lekcjach` / `wolne` | lekcja, następna |
| Następna lekcja | przedmiot | od, do, dzień, sala, nauczyciel |
| Wydarzenia jutro | liczba wpisów z kalendarza szkolnego na jutro | tytuł, opis (np. co przynieść), godzina |
| Najbliższe wydarzenie | tytuł | opis, start, koniec, za ile dni |
| Nieprzeczytane wiadomości | liczba | – |
| Ogłoszenia | liczba | najnowsze, lista |

„Teraz”, „Następna lekcja” i czujniki binarne przeliczają się co minutę bez odpytywania serwera.

**Czujniki binarne:** Lekcje dzisiaj, W szkole teraz (od początku pierwszej do końca ostatniej lekcji).

**Kalendarze:** *Wydarzenia szkolne* (wpisy nauczycieli: sprawdziany, co przynieść, wyjścia) oraz *Plan lekcji*
(bieżący tydzień powtarzany na kolejne tygodnie, bez zastępstw i dni wolnych). Oba można pokazać razem
z innymi kalendarzami na karcie kalendarza.

Strona nie podaje dat ocen. Dlatego „nowa ocena” oznacza ocenę, która pojawiła się od poprzedniego
odczytu. Przy pierwszym uruchomieniu nic się nie zgłasza: integracja tylko zapamiętuje stan.

## Zdarzenia do automatyzacji
- `prymus_nowa_ocena` z danymi: `przedmiot`, `kategoria`, `ocena`, `wykryto`
- `prymus_nowa_uwaga` z danymi: `id`, `data`, `temat`, `status` (pozytywna/negatywna/neutralna)
- `prymus_nowe_wydarzenie` z danymi: `tytul`, `opis`, `start`, `koniec`, gdy w kalendarzu szkolnym pojawi się nowy wpis

```yaml
alias: Prymus – nowa ocena
triggers:
  - trigger: event
    event_type: prymus_nowa_ocena
actions:
  - action: notify.mobile_app_TWOJ_TELEFON
    data:
      title: "Nowa ocena: {{ trigger.event.data.ocena }}"
      message: "{{ trigger.event.data.przedmiot }} – {{ trigger.event.data.kategoria }}"
```

```yaml
alias: Prymus – plecak na jutro
triggers:
  - trigger: time
    at: "19:00:00"
conditions:
  - condition: numeric_state
    entity_id: sensor.prymus_e_dziennik_lekcje_jutro
    above: 0
actions:
  - action: notify.mobile_app_TWOJ_TELEFON
    data:
      title: "Jutro {{ states('sensor.prymus_e_dziennik_lekcje_jutro') }} lekcji, od {{ state_attr('sensor.prymus_e_dziennik_lekcje_jutro','pierwsza') }}"
      message: >-
        {{ state_attr('sensor.prymus_e_dziennik_lekcje_jutro','lekcje') | map(attribute='przedmiot') | unique | join(', ') }}
        {% for e in state_attr('sensor.prymus_e_dziennik_wydarzenia_jutro','wydarzenia') or [] %}
        • {{ e.tytul }}{% if e.opis %}: {{ e.opis }}{% endif %}{% endfor %}
```

## Uwagi
- Pierwsze logowanie może potrwać do minuty. Po powrocie z logowania (OAuth) panel `h0X.prymus.net`
  przez chwilę odsyła na „wybór ucznia”, zanim wpuści do panelu, więc integracja cierpliwie czeka.
  Przy problemach uruchom `tools/test_login.py` (instrukcja w pliku). Wypisze cały przebieg logowania.
- Hasło jest zapisane w konfiguracji HA (`.storage/core.config_entries`), tak jak w innych integracjach chmurowych.
- Gdy zmienisz hasło w dzienniku, HA poprosi o nowe.
- To nieoficjalne rozwiązanie oparte na HTML-u strony, więc zmiana wyglądu dziennika może je zepsuć.
  Wszystkie selektory są w `parser.py`.
