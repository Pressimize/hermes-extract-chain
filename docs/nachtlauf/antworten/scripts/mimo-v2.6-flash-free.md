## Befunde (nach Schwere)

**1. Bug — replay.py:42–44**
`json.loads(detail)` kann auch `None` oder eine Liste liefern (z. B. Keenable-Antwortkörper `null` oder `["timeout"]`). Danach ruft `body.get(...)` ein `AttributeError` aus, das nur von `except ValueError` (Zeile 45) nicht abgefangen wird — der gesamte Replay-Lauf bricht in der Mitte ab, die Vergleichstabelle fehlt.
*Fix:* `except (ValueError, AttributeError)` bzw. vorher `isinstance(body, dict)` prüfen.

**2. Bug — live_check.py:104–106**
`by_host` ist nur nach Hostname Schlüssel; bei zwei URLs desselben Hosts in einem oder über mehrere Calls (z. B. `example.com/a` via TinyFish, `example.com/b` via Keenable) behält das Dict nur die letzte Logzeile. Fall (a) sieht dann die Zeile von (b): Der Check in Zeile 108 meldet fälschlich „Keenable result without note", der gedruckte Provider-Status stimmt nicht.
*Fix:* Zuordnung je Call pro URL aufbauen (z. B. Host→Zeile nur innerhalb einer Gruppe und bei Kollisionen nicht überschreiben).

**3. Edge Case — live_check.py:88**
`asyncio.run(web_extract_tool(...))` steht ohne `try` in der Hauptschleife. Wirft ein Call (Timeout, Verbindungsfehler aus Hermes-Internem), bricht der ganze Lauf ab: Rate-Auswertung (115–127) und `problems:` laufen nie, bereits geschriebene JSONL-Zeilen bleiben ohne Auswertung.
*Fix:* Je Gruppe try/except, Fehler in `problems` aufnehmen, weitermachen.

**4. Edge Case — live_check.py:102–105**
Bei Reihenfolgen-/Zahlabweichung (in 102–103 schon gemeldet) paarzt `zip(..., strict=False)` Ergebnisse weiter mit den falschen Cases; der Keenable-Note-Check und die Ausgabe in 108–112 werten dann fremden Content aus und erzeugen Schein-Probleme.
*Fix:* Bei URL-Mismatch die Per-Case-Checks überspringen oder über `res.get("url")` zuordnen.

**5. Edge Case — replay.py:65–74**
`norm()` normalisiert keine typografischen Varianten: Schlusssatz mit `…`, „…" oder `—` vs. gespeicherter Text mit `...`, `--` etc. → trotz vollständigem Artikel „no" (Vergleich prototype/plugin verzerrt).
*Fix:* In `norm()` auch `…→...`, typografische Anführungszeichen und Gedankenstriche mappen.

**6. Best Practices — live_check.py:28**
`KEENABLE_NOTE` ist hartkodiert und dupliziert die Plugin-Konstante (replay.py:25 importiert `NOTE_KEENABLE` korrekt aus `extract_chain`). Ändert sich der Notiztext im Plugin, schlägt der Check in Zeile 108 still nie mehr an.
*Fix:* Wie in replay.py aus `extract_chain` importieren.

**7. Edge Case — live_check.py:27**
Ohne `HERMES_ROOT` und außerhalb Windows ist `LOCALAPPDATA` leer → `ROOT` wird „hermes" relativ zum CWD. Existiert dort ein solches Verzeichnis, wird die falsche Installation geladen (sonst ein verwirrender Import-Fehler).
*Fix:* Fehlen von `LOCALAPPDATA`/`HERMES_ROOT` als harten Abbruch prüfen.

**8. Edge Case — replay.py:71–74**
Leerer Schlusssatz in `CLOSING` (`""`): `norm("") in c` ist immer wahr → Artikel zählt immer als vollständig, die Gesamtzahl in Zeile 113 ist aufgebläht.
*Fix:* Leere Sätze verwerfen bzw. als Konfigurationsfehler melden.

**9. Stil — live_check.py:111–112**
Die Gruppendauer wird für jeden Case der Gruppe gedruckt (`42.0 s` bei 5 URLs), obwohl kein einzelne URL 42 s braucht — Auswertung irreführend.
*Fix:* Dauer nur einmal pro Gruppe oder als `group=` kennzeichnen.

**10. Stil/Performance — live_check.py:113**
`time.sleep(pace * len(urls))` läuft auch nach der letzten Gruppe (Standard bis 37.5 s sinnlose Wartezeit am Ende).
*Fix:* Nur zwischen Gruppen schlafen.
