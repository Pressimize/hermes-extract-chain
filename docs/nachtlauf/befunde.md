# Nachtlauf 2026-10-16/17: Befunde

Jeder Befund wurde am Code von `main` (`c9d5739`) geprüft, wo möglich mit einem Skript oder Test reproduziert. Mehrfachnennungen sind zusammengeführt. Modellkürzel: SB = space-bunny-free, DS = deepseek-v4.1-flash-free, GLM = glm-5.3-flash-free, MM = mimo-v2.6-flash-free, LC = longcat-2.5-preview-free, BP = big-pickle, BE = beam-free, eigen = von mir beim Lesen gefunden.

Urteile: **bestätigt** (nachvollzogen und reproduziert), **abgelehnt** (mit Grund), **unklar**.

## Bestätigt und behoben

| ID | Kategorie | Fundstelle | Modelle | Urteil und Beleg | Commit |
|---|---|---|---|---|---|
| N01 | Bug + Performance | `extract_chain/chain.py:68` (`_TAGS = <[^>]*>`) | eigen, DS, BP¹ | **bestätigt.** Das Muster entfernt alles zwischen einem `<` im Text und dem nächsten `>`. Ein Artikel von 3.270 Zeichen mit `x < 10` und später `->` hatte 10 sichtbare Zeichen und galt als `empty`; ein Python-Text mit `` `a < b` `` und `>>> 1 < 2` galt als `thin`. Folge: TinyFishs vollständiger Text wird verworfen, Firecrawl (1 Credit) und ggf. Keenable werden gefragt, schlimmstenfalls kommt ein Fehler. Außerdem quadratisch bei vielen `<` ohne `>`: 320 kB → 13 s CPU, in der Event-Loop, also für alle URLs des Aufrufs. Fix: Ein Tag beginnt mit Buchstabe, `/` oder `!` und enthält kein weiteres `<`. Tests `test_less_than_sign_is_no_tag`, `test_many_less_than_signs_classify_in_linear_time` (vorher rot, jetzt grün). | `3fc5a0e` |
| N02 | Robustheit | `extract_chain/fetchers.py:153-154` | SB, DS | **bestätigt.** `{"success": true, "data": "x"}` oder `metadata: "nope"` ergibt `Firecrawl: AttributeError` mit Code `AttributeError` statt des dokumentierten `malformed` (TinyFish und Keenable melden seit 0.2.4 `malformed`). Das Ergebnis war schon vorher ein Fehler; nur Text und Logcode ändern sich. Test `test_firecrawl_data_that_is_no_object_is_malformed`. | `4b16542` |
| N03 | Doku | `docs/troubleshooting.md:145` | eigen | **bestätigt.** Die Edge-Case-Tabelle sagte, eine Seite mit „Access denied“ oder Challenge-Text werde nicht erkannt. Seit 0.2.5 (E7) wird sie unter 1.500 sichtbaren Zeichen als Bot-Check erkannt. Text angepasst. | `e59b4c6` |
| N04 | Bug (Entwicklerskript) | `scripts/replay.py:41-45` | SB, DS, GLM, MM | **bestätigt.** Ein gespeicherter Fehler wie `Keenable fetch failed: 402` oder `… null` ist gültiges JSON, aber kein Objekt; `body.get` wirft `AttributeError`, das Replay bricht ab, bevor die Tabelle gedruckt wird. Reproduziert. Test `test_replay_error_detail`. | `5cb77d1` |
| N05 | Bug (Entwicklerskript) | `scripts/live_check.py:104-109` | eigen, SB, DS, GLM, MM, LC | **bestätigt.** L1-Zeilen nennen nur den Host. Bei zwei URLs desselben Hosts in einem Aufruf überschreibt die letzte Zeile die erste: Eine TinyFish-Antwort wurde gegen die Keenable-Zeile der anderen URL geprüft und als „Keenable result without note“ gemeldet (alte Logik nachgestellt: Fehlalarm `a`), oder eine wirklich fehlende Note fiel nicht auf. Fix: URLs desselben Hosts werden gemeinsam geprüft (Anzahl Ergebnisse mit Note ≥ Anzahl Zeilen mit Keenable-Ergebnis); die Prüfung steckt jetzt in `check_call()`. Tests `test_live_check_*`. | `6dfcd9a` |

¹ Big Pickles erste `chain`-Antwort hatte die Antworten von SB und DS gelesen und den bereits umgesetzten Fix im Arbeitsbaum gesehen; sie zählt nicht als unabhängige Bestätigung.

## Vorschläge, die Andres Entscheidung brauchen

Keine. Kein bestätigter Befund hätte die Schnittstelle oder das dokumentierte Verhalten geändert. N01 ändert die Klassifikation nur für Texte, deren sichtbare Länge bisher falsch gemessen wurde; Marker, Grenzwerte, Hinweise und Reihenfolge bleiben gleich. Das Replay auf den unveröffentlichten Rohdaten (T2) konnte ich nicht laufen lassen; siehe Zusammenfassung.

## Abgelehnt

Gruppiert nach Grund. Jede Zeile ist ein zusammengeführter Befund; in Klammern die Modelle, die ihn nannten.

### A. Bewusste, dokumentierte Entscheidung (`docs/design.md`)

| ID | Befund | Modelle | Grund |
|---|---|---|---|
| A01 | Wall-/Paywall-Marker im Roh-Text statt im sichtbaren Text suchen; `WHOLE_BELOW`/`WALL_WINDOW` messen Roh-Zeichen (`chain.py:96-100`) | SB, BP, GLM | E3 legt ausdrücklich „raw `content` (Markdown or HTML, uncleaned)“ fest. Die Anbieter liefern Markdown (A1–A3, S4); die konstruierten Beispiele mit `<script id="consent-manager">` setzen Roh-HTML voraus, das keiner der drei Dienste so liefert. |
| A02 | Ein einziger Bot-Check-Marker unter 1.500 Zeichen reicht für `challenge`; ein echter Kurzartikel über Captchas bekommt V11 (`chain.py:94`) | SB, BP | E7, D21, D25 und „Known limitations“ beschreiben genau diesen Zielkonflikt; deshalb wird die Seite mit V11 trotzdem zurückgegeben. |
| A03 | Redirect-Hinweis bei jedem Host-Wechsel (`m.`-Subdomain) und jedem zweibuchstabigen Pfadsegment (`/in/`, `/it/`) (`chain.py:111-118`) | SB, BP, GLM | V10 spezifiziert genau diese Regeln; ein Hinweis ändert weder Klasse noch Kette (D22). |
| A04 | Redirect-Hinweis enthält die volle End-URL samt Query (mögliches Token im Modellkontext) (`chain.py:127`, `fetchers.py:121`) | SB, DS, BP | V10 bewusst: Das Modell soll sehen, wohin weitergeleitet wurde. Die Logzeile (L1) ist der Ort, an dem URLs bewusst fehlen; Hermes weist URLs mit Geheimnissen vor jedem Abruf ab. |
| A05 | Pause springt um 00:05:00 UTC von Sekunden auf 24 h (`provider.py:57`) | SB | K7: Ein 402 nach 00:05 bedeutet, dass das neue Tageskontingent verbraucht ist; die fünf Minuten decken nur Uhrabweichungen. |
| A06 | `register()` fängt `ImportError` der Basisklasse nicht ab (`__init__.py:6`) | SB | In „Known limitations“ beschrieben: ohne `agent.web_search_provider` lädt das Plugin nicht. |
| A07 | Block nach Redirect ersetzt die Metadaten des Ergebnisses; Ausnahmetyp im Block-Text (`provider.py:73-88, 160-164`) | BP | S7 und D19 bewusst. |
| A08 | `TINYFISH_API_KEY` heißt „required“, die Kette läuft aber ohne ihn weiter (`plugin.yaml`, `provider.py:108`) | BP | K1 und troubleshooting.md („Missing TinyFish key“) beschreiben das. |
| A09 | Einzel-URL-Fallback ordnet eine Antwort mit anderer URL (auch ein `errors`-Eintrag oder einer ohne `url`) der angefragten URL zu (`fetchers.py:129-130`) | SB, DS, GLM, BP | A1 ausdrücklich (Redirects bei einer einzelnen URL). |
| A10 | Bei einer URL in `results` und `errors` gewinnt immer der Fehler; Antwort ohne `results`/`errors` wird `no_result` statt `malformed`; Batch-Redirect ergibt `no_result` (`fetchers.py:107-135`) | GLM, BP, LC | A1 („errors[] after results[]“, „a results or errors that is no list counts as empty“) und troubleshooting.md („Redirect inside a multi-URL batch“). |
| A11 | TinyFish-Code über 40 Zeichen wird `fetch_failed`; Transportcodes sind Klassennamen in CamelCase (`fetchers.py:40, 57-60`) | GLM | A1 und L1 dokumentiert. |
| A12 | Ausnahmemeldung statt nur Klassenname in `extract-chain: <Klasse>` (`chain.py:219-221`) | BE | S6 bewusst: Die Meldung kann URL oder Seiteninhalt enthalten. |

### B. Hypothetisch: Eingaben, die weder Hermes noch die Anbieter liefern

| ID | Befund | Modelle | Grund |
|---|---|---|---|
| B01 | Firecrawl `success` als String `"false"`, `statusCode` als String `"404"` oder `true` (`fetchers.py:150, 156`) | SB, GLM, LC, BE | Firecrawl v2 liefert `success` als Boolean und `statusCode` als Zahl; dafür gibt es keinen Beleg. |
| B02 | Firecrawl HTTP 200 ohne `success`: Body landet im Fehlertext, Code `api_200`, `status: 200` (`fetchers.py:150-152`) | SB, DS, GLM | Reproduzierbar, aber kein Fehlverhalten: Das Ergebnis ist korrekt ein Fehler, die Kette geht zu Keenable; K7 reagiert nur auf 402. |
| B03 | Sehr kurzer API-Key (z. B. `login`) zerstört TinyFish-Codes bei der Schwärzung; Ersetzungsreihenfolge im Set (`fetchers.py:46-47`) | SB, BE | Nur mit künstlichen Keys reproduzierbar; echte Keys sind lange Zufallszeichenfolgen. |
| B04 | `pdf_pages` kein 2-Tupel, `content` kein String, Dokument der Klasse `error` ohne `error`-Schlüssel, falsy `code` (`chain.py:124, 153, 171`) | SB, BP, GLM, DS, BE | Diese Dicts entstehen nur in `fetchers.py`, das die Typen garantiert (Tests in `test_fetchers.py`). |
| B05 | HTML-Entities (`&nbsp;`), `<script>`/`<style>`-Inhalte zählen als sichtbarer Text (`chain.py:83`) | DS, SB, BP | Die Dienste liefern Markdown. Schlimmste Folge wäre eine zusätzliche Firecrawl-Abfrage bei einer konstruierten Seite. |
| B06 | `urls` als Iterator/Generator, Nicht-String-Objekte in `urls`, `metadata`/`first[url]`/`finalURL` fehlen oder sind kein String (`provider.py:121-162`) | DS, SB, BE | Hermes übergibt eine Liste von Strings (`_validate_extract_urls`); `run_chain` setzt `metadata` immer, `fetchers.tinyfish` liefert für jede URL ein Dokument, `finalURL` wird nur für Strings gesetzt. |
| B07 | Block-Meldung ohne Präfix „Blocked by website policy“ lässt den Keyless-Rescue blockierte URLs holen; Verweigerungs-Einträge ohne `blocked_by_policy` (`provider.py:85, 120`) | SB | Widerlegt am Hermes-Quelltext v0.21.6: `tools/website_policy.py:183` beginnt die Meldung immer mit „Blocked by website policy“, und `tools/web_tools_rescue.py:121-124` erkennt Blöcke an einem nicht leeren `blocked_by_policy` *oder* am kleingeschriebenen Text. |
| B08 | Fallback ohne `tools.interrupt` bleibt still (`provider.py:42-45`) | SB | Das Modul existiert in Hermes ≥ 0.21; S8 ist ausdrücklich „best effort“. |
| B09 | `KeyError` bei 402-Dokumenten ohne `error`/`code`, Lücke in `done` (`provider.py:133, 191-192`) | DS, BP, BE | Invarianten heute garantiert (`fetchers._error`, `zip(..., strict=True)`). |
| B10 | Skripte: JSON-Antwort von `web_extract_tool` kein String, `null`-Einträge, leere/fehlerhafte Zeilen in Rohdaten, leere Schlusssatz-Listen, `AnnAssign`, Zero-Width-Zeichen, Logzeile ohne Host (`live_check.py`, `replay.py`) | DS, GLM, MM, LC, BP, BE | `web_extract_tool` ist als `-> str` deklariert (Hermes `tools/web_tools.py:392`); jede Plugin-Zeile mit Präfix `extract-chain ` enthält einen Host; die Replay-Daten sind fest und liefen bereits (validation.md). |
| B11 | Leere URL-Liste an TinyFish; Duplikate über Batch-Grenzen (`fetchers.py:89-93`) | DS, GLM | `provider.extract` dedupliziert und ruft die Kette nur mit nicht leerer Liste auf. |

### C. Sachlich falsch

| ID | Befund | Modelle | Grund |
|---|---|---|---|
| C01 | Pause mit `left == 0` gelte fälschlich als beendet (`provider.py:182`) | BP | Bei `left == 0` ist die Pause zu Ende; das ist richtig. |
| C02 | `_json` fängt `UnicodeDecodeError` nicht (`fetchers.py:64-67`) | BE | `UnicodeDecodeError` ist eine Unterklasse von `ValueError` (geprüft). |
| C03 | Pausengrund und Logcode könnten Keys enthalten (`provider.py:191-192`) | BP, BE | Der Grund ist der bereits geschwärzte, einzeilige Fehlertext aus `fetchers._error`; Codes stammen aus einer festen Menge bzw. `_CODE`. Auch der Keenable-JSON-Fehlerpfad schwärzt (nachgeprüft). |
| C04 | `record.getMessage()` verfälsche das Präfix; Keenable `ok` mit leerem Inhalt; Fehler mehrzeilig in Hinweisen (`live_check.py:53, 108`, `chain.py:150-153`) | LC, BP, GLM | `getMessage()` liefert genau die formatierte Zeile, die der Filter braucht; `ok` heißt nicht leer und trägt V4; Anbieterfehler sind nach A4 einzeilig und gekürzt. |
| C05 | `_left(3600)` ergebe fälschlich „60 min“ (`provider.py:67`) | DS, BE | 60 min ist korrekt; nur die Grenze „unter einer Stunde“ ist Geschmackssache. Kein Fehlverhalten. |

### D. Performance ohne messbare Wirkung

| ID | Befund | Modelle | Grund |
|---|---|---|---|
| D01 | `_redact` und `" ".join(text.split())` über Megabyte-Fehlerseiten (`fetchers.py:43-53`) | SB, DS, LC, BE | Gemessen: 4 MB → 0,3–0,7 s, linear; bewusst getestet (`test_megabyte_error_page_gives_a_short_error`). Vorab kürzen könnte einen Key an der Schnittkante teilen. |
| D02 | `_visible` wird je URL mehrfach berechnet (`chain.py:91, 152, 197-202`) | SB, DS, BP, BE | Nach N01 linear; D18 misst 13 ms je 100.000 Zeichen. |
| D03 | `deepcopy` jedes Eintrags (`provider.py:133`) | SB, BP | `deepcopy` kopiert Strings nicht; S5 verlangt eigene Objekte je Position. |
| D04 | O(n²)-Ratenfenster, Schlaf nach der letzten Gruppe, `raw` in `results.jsonl` (`live_check.py`) | BP, MM, SB | Entwicklerskript mit höchstens ~100 URLs; `raw` ist gewollt (Ausgabe, wie das Modell sie sieht). |

### E. Entwicklerskripte: gewollt oder ohne Fehlverhalten

| ID | Befund | Modelle | Grund |
|---|---|---|---|
| E01 | `live_check`: kein `try` um `asyncio.run`; nach „order/count“ wird weiter verglichen; Parsefehler erscheint als „order/count“ | SB, MM, GLM, LC | Das Problem wird gemeldet, jede Zeile ist sofort geflusht; Hermes fängt Fehler im Werkzeug selbst ab. |
| E02 | `KEENABLE_NOTE` kopiert statt importiert | SB, GLM, MM | `live_check.py` läuft mit `-I` im Python von Hermes; ein Import aus dem Repo ist bewusst vermieden. V4 steht immer als erste Hinweiszeile. |
| E03 | `results.jsonl` im Append-Modus; Ausgabeverzeichnis im Repo möglich | DS, GLM, BE, SB, LC | Anhängen ist gewollt (Läufe sammeln); `out/` steht in `.gitignore`, der Docstring warnt. |
| E04 | `ROOT` relativ ohne `HERMES_ROOT`/`LOCALAPPDATA`; `assert` statt `SystemExit`; Root-Level INFO | SB, GLM, MM, DS, LC | Dokumentiert (Windows-Pfad, Überschreiben mit `HERMES_ROOT`); Fehler kommt sofort beim Import. Aufruf mit `-I`, nicht `-O`. |
| E05 | Alle `*_API_KEY` werden aus der Umgebung entfernt | BP | Gewollt (Docstring: Keys nur aus dem Profil). |
| E06 | Prototyp bekommt rohe Daten und synchrone Lambdas, Plugin normalisierte Daten; `exec_module` lädt beliebigen Code | SB, BE | Jede Seite bekommt ihr eigenes Format; der Prototyp ist eigener Code des Autors. |

### F. Stil und Testlücken ohne Fehler

Namen (`short`, `page`, `check`), Literale für Anbieternamen, ternärer Ausdruck als Iterable, wiederholte Zweizeiler, magische Slices in den Skripten, `if not 0 < left <= DAY`, Eindeutigkeitstest der Marker ohne `CHALLENGE` und ohne Regex-gegen-Regex-Vergleich (SB, DS, BP, GLM, BE, LC). Kein Fehlverhalten nachgewiesen; Änderungen wären Geschmack.

## Unklar

Keine.

## Zählung

- Antworten mit Befunden: 24 (dazu eine leere von Longcat und eine nicht unabhängige von Big Pickle).
- Einzelpunkte in diesen Antworten: rund 180; nach Zusammenführen 5 bestätigt (N01–N05; N01, N03 und N05 hatte ich auch selbst beim Lesen gefunden) und rund 40 abgelehnte Themen (A–F).
- Bestätigt von mehreren Modellen unabhängig: N04 (4 Modelle), N05 (5 Modelle), N02 (3 Modelle). N01 fand nur DeepSeek unabhängig; GLM, Beam und Space Bunny übersahen ihn im selben Bereich.
