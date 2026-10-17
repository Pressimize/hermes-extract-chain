# Nachtlauf 2026-10-16/17: Zusammenfassung

## Kurz und ohne Fachbegriffe

Ich habe das Plugin über Nacht von sieben kostenlosen KI-Modellen prüfen lassen und jeden ihrer Hinweise selbst nachgeprüft. Von rund 180 Hinweisen hielten nur wenige stand; die meisten wiederholten bewusst getroffene Entscheidungen oder beschrieben Fälle, die in der Praxis nicht vorkommen.

**Behoben (5 Punkte):**

1. **Programmier-Artikel wurden fälschlich als leer verworfen.** Enthielt ein Text ein Kleiner-Zeichen (etwa „x < 10“) und weiter hinten ein Größer-Zeichen, hielt das Plugin alles dazwischen für unsichtbaren Seitencode. Ein vollständiger Artikel galt dann als leer oder sehr kurz, und das Plugin fragte unnötig den nächsten, kostenpflichtigen Dienst. Bei sehr vielen Kleiner-Zeichen konnte die Prüfung außerdem mehrere Sekunden Rechenzeit kosten. Das ist der wichtigste Fund der Nacht.
2. **Eine kaputte Antwort von Firecrawl** erzeugte eine unverständliche Fehlermeldung statt der vorgesehenen („malformed reply“). Das Ergebnis war vorher schon ein Fehler; jetzt ist er richtig benannt.
3. **Eine veraltete Zeile in der Fehlerhilfe** (`docs/troubleshooting.md`) sagte, Bot-Schutzseiten würden nicht erkannt. Das stimmt seit Version 0.2.5 nicht mehr.
4. **Das Nachprüf-Skript `replay.py`** brach bei bestimmten gespeicherten Fehlermeldungen ab.
5. **Das Live-Prüfskript `live_check.py`** ordnete bei zwei Adressen derselben Website die Protokollzeilen falsch zu und meldete dadurch Scheinprobleme oder übersah echte.

Die Punkte 4 und 5 betreffen nur Werkzeuge für Entwickler, nicht das ausgelieferte Plugin. An Bedienung, Einstellungen, Werkzeugnamen und Reihenfolge der Dienste hat sich nichts geändert. Keine neue Version, nichts veröffentlicht.

**Was Andre entscheiden sollte:** Am Plugin nichts. Am Prüfwerkzeug `scripts/second-opinion.sh` gibt es Vorschläge (siehe unten). Wichtigster: Die Modelle konnten die Antworten der anderen Modelle lesen, und eines hat das nachweislich getan.

## Was gemacht wurde

**Phase 0.** `scripts/second-opinion.sh` auf `chore/second-opinion`: `mktemp -d` wird geprüft; doppelte Anhänge werden per exaktem Namensvergleich erkannt (ohne Glob); ein Anhang `<modell>.md` oder `<modell>.log` bricht mit Meldung ab; `flock` auf `.opinion.lock` verhindert parallele Läufe (`.opinion.lock` steht in `.git/info/exclude`). Kurz getestet (Duplikat, Kollision, Sperre, ein echter Modellaufruf). PR [Pressimize/hermes-extract-chain#1](https://github.com/Pressimize/hermes-extract-chain/pull/1) per Squash gemergt (`c9d5739`), `main` aktualisiert.

**Phase 1.** Branch `review/nachtlauf-2026-10-16` von `main`. Testsuite vorher: 176 bestanden, `ruff` sauber. Vier Prüfbereiche: `fetchers`, `chain`, `provider` (mit `__init__.py`, `plugin.yaml`, `conftest.py`) und `scripts`, je Code plus Tests unter 800 Zeilen (`plan.md`).

**Phase 2.** Je Bereich alle verfügbaren Modelle gefragt.

| | |
|---|---|
| Modelle mit Antwort | space-bunny-free, deepseek-v4.1-flash-free, glm-5.3-flash-free, mimo-v2.6-flash-free, longcat-2.5-preview-free, big-pickle, beam-free (neu, unbewertet) |
| Nicht mehr verfügbar | muse-spark-1.3-contributor-free, cat-jam-free, ll-alpha-free („Model not found“) |
| Bewusst nicht gefragt | Nemotron (laut `CLAUDE.md`) |
| Aufrufe | 51 |
| Antworten | 26, davon 24 verwertbar (eine leere von Longcat, eine nicht unabhängige von Big Pickle). Die leere Longcat-Antwort zu `provider` (drei Zwischensätze) wurde beim Speichern von der Wiederholung überschrieben. |
| Rate-Limits | 3 (alle im ersten Durchgang, DeepSeek, GLM, MiMo); später keine mehr |
| Timeouts | 13 (MiMo 6, Big Pickle 3, GLM 2, Longcat 2) |
| Sonstige Fehler | 7× „Model not found“, 2× leere Ausgabe (Longcat) |
| Wiederholungen | eine Runde für alle Lücken; danach keine weitere |

Abdeckung (✓ = verwertbare Antwort):

| Bereich | SB | DS | GLM | MM | LC | BP | BE |
|---|---|---|---|---|---|---|---|
| fetchers | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| chain | ✓ | ✓ | ✓ | – | – | (✓)¹ | ✓ |
| provider | ✓ | ✓ | ✓ | – | ✓² | ✓ | ✓ |
| scripts | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

¹ nicht unabhängig, zählt nicht. ² erst in der Wiederholung.

**Änderungen am Ablauf während der Nacht** (Details in `plan.md`):

- Um 00:45 stellte sich heraus, dass Big Pickle im Bereich `chain` per `cat .opinion/deepseek-…md .opinion/space-bunny-free.md` die Antworten der beiden Vorgänger gelesen und übernommen hatte (nachgewiesen in der Sitzungsdatenbank von opencode). Die Modelle laufen im „build“-Modus mit Shell-Zugriff, lesen das ganze Repo (also auch schon umgesetzte Fixes) und führen Tests aus. Ab da habe ich jedes Modell einzeln aufgerufen (`OPINION_MODELS=<modell> OPINION_POOL=" " OPINION_COUNT=1`; das Skript leert `.opinion/` dann vor jedem Modell), die Originaldateien von `main` angehängt und bereits erhaltene Antworten außerhalb des Repos gelagert. Das Skript selbst habe ich nach Phase 0 nicht mehr geändert.
- `OPINION_TIMEOUT=900` statt 400.
- Ab 01:25 enthielten die Prompts die Zeile „Prüfe ausschließlich die angehängten Dateien … führe keine Befehle aus“. Danach waren die Antworten deutlich schneller (Beam 20–66 s, Space Bunny 55 s, DeepSeek 50–115 s).

**Phase 3.** Jeden Punkt am Code geprüft, Reproduktionen per Skript oder Test, zwei Behauptungen über Hermes am Quelltext von Hermes v0.21.6 überprüft (Website-Blocklist und Keyless-Rescue). Ergebnis in `befunde.md`.

**Phase 4.** Fünf Fixes, je ein Commit mit Befund-ID, jeweils erst roter Test, dann Fix. Testsuite nachher: 187 bestanden (11 neue Tests), `ruff check` und `ruff format --check` sauber. Keine neuen Abhängigkeiten, Version unverändert (`CHANGELOG.md` hat einen Abschnitt „Unreleased“).

## Umgesetzte Fixes

| ID | Problem | Auswirkung | Getestet |
|---|---|---|---|
| N01 | `chain.py` entfernte zum Messen der sichtbaren Länge alles zwischen einem `<` im Text und dem nächsten `>`; das Muster war zudem quadratisch. | Programmier-Artikel (`x < 10`, `>>> 1 < 2`) galten als `empty`/`thin`, TinyFishs Text wurde verworfen und Firecrawl (1 Credit) und ggf. Keenable gefragt; 320 kB mit vielen `<` kosteten 13 s CPU in der Event-Loop. Jetzt zählt nur `<` + Buchstabe/`/`/`!` ohne weiteres `<` als Tag; linear. | `test_less_than_sign_is_no_tag`, `test_many_less_than_signs_classify_in_linear_time` (vorher rot) |
| N02 | Firecrawl-Antwort mit `data`/`metadata`, das kein Objekt ist, ergab `Firecrawl: AttributeError`. | Jetzt `Firecrawl: malformed reply` mit Code `malformed`, wie bei TinyFish und Keenable. Die Kette verhält sich gleich (Keenable ist dran). | `test_firecrawl_data_that_is_no_object_is_malformed` (3 Fälle, vorher rot) |
| N03 | `troubleshooting.md` beschrieb Bot-Check-Seiten als nicht erkannt. | Doku entspricht wieder E7. | Abgleich mit `docs/design.md` E7 und `chain.py` |
| N04 | `replay.py` brach bei einem gespeicherten Fehlerdetail ab, das JSON, aber kein Objekt ist (`402`, `null`). | Replay läuft weiter und druckt die Tabelle. | `test_replay_error_detail` (4 Fälle, vorher 2 rot) |
| N05 | `live_check.py` ordnete Logzeilen nur nach Host zu. | Bei zwei URLs derselben Website wurde eine TinyFish-Antwort als „Keenable result without note“ gemeldet oder eine fehlende Note übersehen. Jetzt werden URLs eines Hosts gemeinsam geprüft (`check_call()`). | `test_live_check_two_urls_of_one_host`, `test_live_check_one_url_per_host`; alte Logik nachgestellt (Fehlalarm reproduziert) |

**Nicht geprüft:** Das Replay auf den unveröffentlichten Rohdaten (T2) und der Live-Check (T3) konnten hier nicht laufen. N01 ändert die Klassifikation nur für Texte mit einem `<`, auf das später ein `>` folgt; ein Lauf von T2 vor dem nächsten Release würde zeigen, ob einer der gespeicherten Artikel betroffen war.

## Vorschläge, die Andres Entscheidung brauchen

**Am Plugin:** keine. Kein bestätigter Befund hätte Schnittstelle oder dokumentiertes Verhalten geändert.

**Am Prüfwerkzeug `scripts/second-opinion.sh`** (nicht umgesetzt, weil das Skript nach Phase 0 nicht weiter bearbeitet werden sollte):

1. **Modelle voneinander trennen.** Jedes Modell in einem eigenen Arbeitsordner laufen lassen (z. B. `.opinion/<modell>/` mit Kopie der Anhänge) oder Antworten erst nach dem Lauf nach `.opinion/` verschieben. Sonst kann ein Modell die Antworten der vorigen lesen; Big Pickle hat das getan.
2. **Werkzeugzugriff begrenzen.** Die Modelle laufen als opencode-Agent „build“ mit Shell und Lesezugriff auf das ganze Repo. Entweder ein Agent ohne Werkzeuge (falls opencode das erlaubt) oder mindestens die Prompt-Zeile „Prüfe ausschließlich die angehängten Dateien …“ fest einbauen; mit ihr wurden die Antworten schneller und unabhängiger vom Arbeitsstand.
3. **Rangfolge aktualisieren.** Muse Spark, Cat Jam und LL Alpha gibt es beim Anbieter derzeit nicht; Beam ist neu. Die Rangfolge ändert laut `CLAUDE.md` nur Andre.
4. **Hänger erkennen.** MiMo startete oft den Antwortstrom und lieferte dann 0 Token bis zum Timeout. Das Skript erkennt nur „Rate limit exceeded“. Eine Prüfung „nach N Sekunden noch keine Ausgabe“ würde 15 Minuten je Hänger sparen.
5. **Timeout.** Mit Werkzeugnutzung reichten 400 s oft nicht; 900 s reichten fast immer, wenn das Modell überhaupt antwortete.

## Abgelehnte Befunde (gruppiert)

Vollständige Liste mit Modellen und Begründung in `befunde.md`, Abschnitt „Abgelehnt“.

| Gruppe | Beispiele | Grund |
|---|---|---|
| A. Bewusste Entscheidung (12 Themen) | Marker im Roh-Text suchen (E3), ein Bot-Check-Marker reicht (E7/D25), Redirect-Hinweis mit voller URL (V10), TinyFish-Pause nach 00:05 volle 24 h (K7), Einzel-URL-Fallback (A1) | in `docs/design.md` begründet; nicht neu aufgerollt |
| B. Hypothetisch (11) | `success` als String, `statusCode` als String, sehr kurze Keys, Iterator statt Liste, Nicht-String-URLs, Block-Meldung ohne Präfix | Hermes und die Dienste liefern solche Eingaben nicht; die Keyless-Rescue-Behauptung ist am Hermes-Quelltext widerlegt |
| C. Sachlich falsch (5) | Pause bei `left == 0`, `UnicodeDecodeError` sei kein `ValueError`, Pausengrund enthalte Keys | nachgeprüft, trifft nicht zu |
| D. Performance ohne Wirkung (4) | Schwärzung über MB-Fehlerseiten, mehrfaches `_visible`, `deepcopy` | gemessen bzw. linear und klein; teils bewusst getestet |
| E. Entwicklerskripte, gewollt (6) | Append-Modus, kopierte Notiz-Konstante, `ROOT` relativ, Keys aus der Umgebung entfernen | so beabsichtigt und dokumentiert |
| F. Stil/Testlücken | Variablennamen, Literale, magische Slices | kein Fehlverhalten |

## Eindrücke je Modell

Punkte = Summe der Einzelpunkte in verwertbaren Antworten; Treffer = davon bestätigt (Mehrfachnennung desselben Befunds in einer Antwort zählt einmal). Einzelzeilen in `docs/modell-eindruecke.md`.

| Modell | Antworten / Versuche | Punkte | Treffer | Tempo | Eindruck |
|---|---|---|---|---|---|
| deepseek-v4.1-flash-free | 4 / 5 | 27 | 4 (N01, N02, N04, N05) | 50–356 s | Bestes Verhältnis von Treffern zu Lärm; einziges Modell, das N01 unabhängig fand, mit Messung. Liest das Design und lässt Dokumentiertes weg. |
| space-bunny-free | 4 / 4 | 37 | 3 (N02, N04, N05) | 55–110 s | Zuverlässig erreichbar, korrekte Zeilen, gründlich; übersieht aber N01 und kritisiert oft dokumentierte Entscheidungen. |
| mimo-v2.6-flash-free | 2 / 9 | 18 | 3 (N02, N04, N05) | 185–386 s | Wenn es antwortet, gut; meistens Hänger ohne ein einziges Token. |
| glm-5.3-flash-free | 4 / 7 | 29 | 2 (N04, N05) | 235–430 s | Solide formuliert, langsam (einmal 49.000 Token Nachdenken ohne Antwort), viele Wiederholungen dokumentierter Punkte. |
| longcat-2.5-preview-free | 4 / 8 (davon 1 leer) | 16 | 1 (N05) | 115–721 s | Langsam und dünn; zweimal leere Ausgabe, einmal nur Zwischentext. |
| big-pickle | 3 / 7 (ohne die kontaminierte) | 25 | 0 | 145–311 s | Viele Punkte, keiner bestätigt; hat einmal fremde Antworten abgeschrieben. |
| beam-free (neu) | 4 / 4 | 28 | 0 | 20–66 s | Mit Abstand am schnellsten und immer erreichbar, knapp und mit korrekten Zeilen, aber keinen echten Fehler gefunden; eine sachlich falsche Aussage. |

Gegenüber der Rangfolge in `CLAUDE.md` (Space Bunny vor DeepSeek) lag DeepSeek in dieser Nacht vorn. Der Eindruck beruht auf vier Bereichen eines kleinen Plugins; die Rangfolge ändert Andre.
