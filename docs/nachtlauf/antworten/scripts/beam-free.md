1. **Edge Case** — `live_check.py:104`: `line.split(" ", 2)[1]` bricht mit `IndexError` ab, wenn eine geloggte Zeile weniger als zwei Tokens hat; der ganze Lauf stoppt. Fix: Zeilen mit unpassendem Format überspringen/`partition` nutzen.

2. **Edge Case** — `replay.py:28` und `:36`: `re.fullmatch`/`str.split` auf `d.get("error")` setzen einen String voraus; ist der gespeicherte Fehler ein Dict/Liste, gibt es `TypeError`/`AttributeError`. Fix: Fehlerwert vorher in `str` umwandeln.

3. **Edge Case** — `live_check.py:102`: `[r.get("url") for r in results]` setzt voraus, dass jedes Element ein Dict ist; ein `null`-Eintrag in der JSON-Antwort lässt das Skript mit `AttributeError` abstürzen statt das Problem zu melden. Fix: `isinstance(r, dict)` prüfen.

4. **Performance/Robustness** — `live_check.py:83`: Datei wird im Append-Modus (`"a"`) geöffnet; wiederholte Läufe vermischen alte und neue Zeilen in `results.jsonl`, was Ratenanalyse und Duplikaterkennung verfälscht. Fix: `"w"` oder explizite Rotation/Truncate.

5. **Security** — `replay.py:49`: `load_function` führt beliebigen Code aus einem vom Benutzer übergebenen Pfad per `exec_module` aus. Fix: Pfad validieren/einschränken oder Aufruf nur auf vertrauenswürdige Dateien.

6. **Edge Case** — `replay.py:99`: Prototyp bekommt `lambda fc=fc: fc` (liefert das Dict), während der Plugin-Pfad asynchrone Fetcher (`fixed(...)`) übergibt; falls der Prototyp die Fetcher awaitet, schlägt der Aufruf fehl. Fix: dieselbe Fetch-Abstraktion wie im Plugin-Pfad verwenden.

7. **Stil** — `replay.py:103`: magische Slices `[16:60]` koppeln die Ausgabe an das genaue Notizformat; bei kürzeren/anderen Notizen werden Ausschnitte falsch oder leer. Fix: anhand von Markern/Präfixen schneiden.

8. **Stil** — `live_check.py:110`/`:111`: magische Indizes `[16:70]` und `split(': ', 1)[-1]` sind formatabhängig; bei abweichender Notiz entstehen falsche/leere Ausgaben. Fix: über benannte Präfixe/Parser auswerten.

9. **Edge Case** — `replay.py:92`: fehlende Argumente führen zu einem unklaren `IndexError` statt einer Nutzungsmeldung. Fix: Argumentzahl prüfen und mit Hinweis abbrechen.
