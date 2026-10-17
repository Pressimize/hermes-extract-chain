## Befunde (nach Schwere sortiert)

1. **Bug (Laufverlust)** — `live_check.py:91-92` — `except (ValueError, AttributeError)` fängt `TypeError` nicht: gibt `web_extract_tool` auf einem Fehlerpfad ein dict oder None statt JSON-String zurück (`json.loads(raw)` → TypeError), stirbt das Skript; die Zeile für die Gruppe wird nie geschrieben (Zeile 96), restliche Gruppen laufen nicht, Rate-/Problems-Ausgabe entfällt. Fix: `TypeError` in das except-Tupel aufnehmen (oder `isinstance(raw, (str, bytes))` vorab prüfen).

2. **Bug / Edge Case** — `replay.py:42-44` — Wenn Keenable einen JSON-Body speichert, der kein Objekt ist (z. B. `null`, `"Fehler"` als JSON-String, ein Array), wirft `body.get("message")` AttributeError; nur `ValueError` wird gefangen → gesamtes Replay bricht ab. Fix: nach `json.loads` auf `isinstance(body, dict)` prüfen, sonst Detail unverändert lassen.

3. **Abweichung von Best Practices** — `live_check.py:74-75` — Laufzeit-Guards als `assert`: außerhalb der dokumentierten `-I`-Aufrufs (z. B. `python -O` oder gesetztes `PYTHONOPTIMIZE`) werden sie übersprungen → der Test läuft mit falscher Backend-Konfiguration und produziert glaubwürdige, aber ungültige Ergebnisse. Fix: explizite Prüfung mit `raise SystemExit(...)`.

4. **Edge Case (Fehlzuordnung)** — `live_check.py:104` — Zwei URLs derselben Gruppe mit gleichem Host: das dict-Comprehension behält nur die letzte Zeile, also wird für beide Fälle dieselbe (die zweite) Provider-Zeile angezeigt; Keenable-Check (108) und Summary-Zeile (111) melden dann das falsche Ergebnis. Fix: Zeilen statt per Host per Positionsindex/Case zuordnen (z. B. `(host, url)`-Key oder Liste je Host).

5. **Robustness (Diagnostik)** — `live_check.py:102-103` — Wenn `json.loads(raw)` misslingt (92-93), ist `results == []` und der entstehende Problem-Text lautet „order/count [...]“ — die wahre Ursache (Parsefehler) ist nicht erkennbar. Fix: Parse-Fehler als eigenen Problem-Typ melden.

6. **Security / Datenleck-Risiko** — `live_check.py:13, 83` — results.jsonl enthält ganze Artikeltexte; „keep it outside git“ ist nur ein Docstring-Hinweis. Wird OUTDIR im Repo (oder wäre zufällig `.`) gewählt, landen urheberrechtlich geschützte Texte committbar im Repo. Fix: OUTDIR ablehnen, wenn er im Git-Worktree liegt (`.git` nach oben suchen), oder per Default unter ein nicht-repo-angebundenes Verzeichnis erzwingen.

7. **Abweichung von Best Practices** — `live_check.py:28, 108` — Keenable-Notiz als dupliziertes String-Literal statt wie in replay.py:25 aus `extract_chain.chain` importiert → bei Notiz-Änderung im Plugin false positives „Keenable result without note“. Fix: Note aus dem Plugin-Modul importieren (sys.path-Insert analog replay.py:24) oder Version mitabgleichen.

8. **Datenmodell** — `live_check.py:83` — Append-Modus mit festem Dateinamen: Rerun in dasselbe OUTDIR mischt Zeilen verschiedener Läufe ohne Markierung; Rate-/Problem-Auswertung betrachtet nur den aktuellen Prozess, die Datei ist aber nicht mehr pro Lauf interpretierbar. Fix: Dateiname pro Lauf (Start-Timestamp) oder alten File bei neuem Lauf umbenennen/schneiden.

9. **Robustness** — `live_check.py:83-128` — Kein `try/finally`: bricht ein späterer Apell (z. B. Befund 1) oder KeyboardInterrupt ab, sind die schon gesammelten `problems` und die Rate-Auswertung verloren (Zeilendaten sind durch `fh.flush()` in 97 erhalten, Probleme nie). Fix: Rate-/Problems-Auswahl oraz Ausgabe in `finally`.

10. **Edge Case** — `live_check.py:27` — Auf Linux ohne `HERMES_ROOT` ergibt `os.path.join("", "hermes")` → `"hermes"` relativ zum cwd, spät und kontextabhängig missverständlich (Import- or Assert-Fehler statt klarer Meldung). Fix: nach `hermes_env`-Setup prüfen `Path(ROOT).is_dir()`, sonst `SystemExit` mit deutlichem Hinweis.

Load not found — URL rejected: protocol https not supported
