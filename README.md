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
| Encja | Stan | Atrybuty |
|---|---|---|
| Liczba ocen | ile ocen bieżących | oceny pogrupowane wg przedmiotu, oceny okresowe, semestr |
| Ostatnia nowa ocena | „Przedmiot: ocena” | kategoria, kiedy wykryto, 10 ostatnich |
| Godziny opuszczone / Nieusprawiedliwione / Spóźnienia | suma w semestrze | podział na miesiące |
| Uwagi | liczba | pozytywne, negatywne, lista |
| Punkty zachowania | suma | wpisy |
| Lekcje dzisiaj / jutro | liczba lekcji | godzina pierwszej i końca ostatniej, lista lekcji z salami |
| Ogłoszenia | liczba | najnowsze (tytuł, autor, data, początek treści) |

Strona nie podaje dat ocen. Dlatego „nowa ocena” oznacza ocenę, która pojawiła się od poprzedniego
odczytu. Przy pierwszym uruchomieniu nic się nie zgłasza: integracja tylko zapamiętuje stan.

## Zdarzenia do automatyzacji
- `prymus_nowa_ocena` z danymi: `przedmiot`, `kategoria`, `ocena`, `wykryto`
- `prymus_nowa_uwaga` z danymi: `id`, `data`, `temat`, `status` (pozytywna/negatywna/neutralna)

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
```

## Uwagi
- Hasło jest zapisane w konfiguracji HA (`.storage/core.config_entries`), tak jak w innych integracjach chmurowych.
- Gdy zmienisz hasło w dzienniku, HA poprosi o nowe.
- To nieoficjalne rozwiązanie oparte na HTML-u strony, więc zmiana wyglądu dziennika może je zepsuć.
  Wszystkie selektory są w `parser.py`.
