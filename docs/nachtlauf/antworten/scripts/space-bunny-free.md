## Befunde (nach Schwere)

**1. Bug/Absturz – `replay.py:42-43`**
`json.loads(detail)` kann erfolgreich parsen und trotzdem kein Dict liefern (z. B. Keenable-Fehlerdetail `"402"`, `"true"` oder ein JSON-Array). Dann wirft `body.get(...)` einen `AttributeError`, der nicht abgefangen wird – der Lauf bricht ab, alle folgenden Artikel werden nicht mehr ausgewertet, und die Tabelle wird nie gedruckt.
*Fix:* `if isinstance(body, dict):` vor dem Auslesen, sonst `detail` unverändert verwenden.

**2. Bug – `live_check.py:88`**
`asyncio.run(web_extract_tool(...))` steht ohne `try`. Jeder Fehler (Interrupt, Timeout, unerwartete Provider-Exception) bricht den Lauf ab: `results.jsonl` enthält nur Teil-Daten, die Pacing-Pause (Zeile 113) entfällt, und Raten-/Problem-Auswertung (115-128) wird nie erreicht. Genau diese Datei soll doch zur Fehlersuche dienen.
*Fix:* `except Exception as e:` → Fehler in `row` und `problems` aufnehmen, Pace trotzdem halten, weiter mit der nächsten Gruppe.

**3. Bug – `live_check.py:104`**
`by_host` ist ein Dict pro Host, d. h. bei zwei URLs derselben Domain in einer Gruppe überschreibt die letzte Logzeile die erste. Die Keenable-Prüfung (Zeile 108) und die Ausgabe (111) werden dann der falschen URL zugeordnet; der Beleg für den ersten Ketten-Schritt geht verloren.
*Fix:* Zeilen pro Host als Liste führen und pro Fall die passende (z. B. positionsgleiche oder URL-enthaltene) Zeile wählen, sonst auf `by_host` verzichten und jede Zeile einzeln prüfen.

**4. Bug – `live_check.py:102-105`**
Nach dem Befund „order/count" wird trotzdem weiter auf `results` gezippt. Bei abweichender Reihenfolge/fehlenden URLs entstehen zusätzliche, sachlich falsche Befunde und eine irreführende Ausgabe.
*Fix:* Nach dem Anhängen des Problems mit `continue` zur nächsten Gruppe springen.

**5. Wartbarkeit/Fehlalarm – `live_check.py:28` + `:108`**
`KEENABLE_NOTE` ist eine Kopie der Plugin-Notiz; `replay.py:25` importiert `NOTE_KEENABLE` dagegen aus dem Plugin. Ändert sich der Notiztext, meldet `live_check` für **jeden** Keenable-Fall „Keenable result without note". Zusätzlich prüft `startswith` nur die erste Zeile, obwohl das Plugin mehrere `[extract-chain]`-Zeilen voranstellen kann (vgl. `replay.py:103`).
*Fix:* `from extract_chain.chain import NOTE_KEENABLE` verwenden und auf `NOTE_KEENABLE in content` prüfen.

**6. Testaussage ungültig – `replay.py:99` vs `:101`**
Der Prototyp bekommt die rohen Hermes-Dicts (inkl. `url`, ungekürztem Fehlertext) über synchrone Lambdas, das Plugin bekommt normalisierte, auf 210 Zeichen gekürzte Docs über `async`-Fetcher. Ein Quellen- oder Vollständigkeitsunterschied kann damit vom Harness statt von der Kette stammen.
*Fix:* Beide Seiten identisch versorgen, z. B. Prototyp mit `tinyfish_doc(tf)` und `fixed(other_doc("Firecrawl", fc))` aufrufen.

**7. Bug – `replay.py:96`**
`.splitlines()` + `json.loads` ohne Schutz: eine Leerzeile (von Hand ergänzt) oder eine abgebrochene Zeile wirft `ValueError` und killt den Lauf, obwohl die Rohdaten nicht veröffentlicht und daher manuell gepflegt sind.
*Fix:* Leerzeilen überspringen, bei Fehlern die Zeilennummer melden und die Auswertung starten.

**8. Security/Datenabfluss – `live_check.py:81` + `:96`**
`os.makedirs(out, exist_ok=True)` akzeptiert beliebige Pfade, und Zeile 96 schreibt mit `raw` die vollständigen Artikeltexte in `results.jsonl` – laut Docstring genau die Daten, die nicht ins Git dürfen. Ein Aufruf mit einem Verzeichnis im Repo legt sie dort ab.
*Fix:* `out` ablehnen, wenn es innerhalb des Repo-Roots liegt (oder in ein temporäres Verzeichnis schreiben und `.gitignore` ergänzen).

**9. Konfiguration – `live_check.py:27`, `:33`**
Ohne `HERMES_ROOT` und ohne `LOCALAPPDATA` (Linux/macOS) wird `ROOT` zum relativen Pfad `hermes`; `sys.path.insert` zeigt dann ins Leere, `load_hermes_dotenv` lädt still nichts, und der Fehler erscheint erst weit später beim Provider-Aufruf.
*Fix:* `os.path.isdir(ROOT)` prüfen und mit klarer Meldung (`HERMES_ROOT` setzen) abbrechen.

**10. Stil/Performance – `live_check.py:74-75`, `:79`, `:113`, `:124`**
Die Vorbedingungen (Backend, Plugin geladen) stehen in `assert` und entfallen unter `-O` – dann misst der Lauf das falsche Backend und liefert stille Scheinwerte. Zeile 79 verschleiert das Level in einem `min(... or INFO, INFO)`. Zeile 113 schläft auch nach der letzten Gruppe, und Zeile 124 ist O(n²) über allen Zeitstempeln, während `rows` (Zeile 82) alle Rohtexte im Speicher hält.
*Fix:* Vorbedingungen per `raise SystemExit` prüfen, Level-Konstante setzen, letzte Gruppe überspringen, Rate-Fenster mit zwei Indizes in einem Durchlauf und `raw` nicht in `rows` halten.
