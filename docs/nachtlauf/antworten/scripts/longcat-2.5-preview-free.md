1. **Bug** — `live_check.py:105` – `zip(group, results)` paart Artikel und Ergebnisse nach Index. Wenn Hermes die Ergebnisse in anderer Reihenfolge liefert (oder einzelne fehlen), werden Log-Zeilen und Notes den falschen Artikeln zugeordnet, ohne dass der Reihenfolge-Check (Zeile 102) das stillschweigend korrigiert. Fix: nach Reihenfolge-Diskrepanz die Zeile überspringen oder dict-basiert anhand der URL matchen.

2. **Bug** — `live_check.py:104` – `by_host`-Dictionary überschreibt Log-Zeilen bei Host-Kollisionen: mehrere URLs derselben Gruppe mit gleichem Host (z.B. `spiegel.de/a`, `spiegel.de/b`) hinterlassen nur die letzte L1-Zeile für alle. Keenable-/Firecrawl-Prüfung (Zeile 108) und Ausgabe (Zeile 111) zeigen dann dieselbe Zeile für unterschiedliche Artikel. Fix: pro-URL statt pro-Host sammeln.

3. **Edge Case** — `live_check.py:53` – `record.getMessage()` evaluiert `%`-Format-Argumente. Falls das Plugin später mit `logging.info("extract-chain %s", x)` loggt, verschlüsselt `getMessage()` das Präfix und der Filter matcht nicht mehr → alle L1-Zeilen gehen verloren, `by_host` bleibt leer. Fix: `record.msg` prüfen oder beide Varianten abfangen.

4. **Bug** — `live_check.py:105` – `res.get("error")` wird im zip-Block nie geprüft. Ein fehlgeschlagener Extrakt, der kein `error`-Feld trägt (z.B. leere `results`), wird stillschweigend übersprungen und erscheint nicht in `problems`. Fix: `if res.get("error"): problems.append(...)`.

5. **Security/Praxis** — `live_check.py:83` – `results.jsonl` mit Artikeltexten landet in `OUTDIR` ohne Lock und ohne `.gitignore`-Logik. Wenn `OUTDIR` innerhalb eines Repo-Checkouts liegt, können sensible Texte versehentlich committet werden. Fix: `OUTDIR` außerhalb des Repos wählen oder eine `.gitignore` mit `results.jsonl` anlegen.

6. **Bug** — `live_check.py:79` – `setLevel(INFO)` auf dem Root-Logger erzwingt auch für fremde Hermes-Handler INFO-Ausgabe. Das kann während des gesamten Laufs unerwünschte Log-Auslöser verursachen. Fix: `Collect` nur auf einen dedizierten Logger setzen oder das Level danach zurücksetzen.

7. **Edge Case** — `replay.py:66` – `norm()` entfernt `\`, `\xad`, `*`, `_`, aber nicht `\u200b`, `\u200c`, `\u200d`, `\ufeff`. Artikel mit Zero-Zeichen oder BOM führen zu false-negativen `complete()`-Ergebnissen. Fix: Zeichensatz erweitern.

8. **Bug** — `replay.py:101` – `tinyfish_doc(tf)` mit `tf=None` (fehlender `tinyfish`-Eintrag in `docs`) wirft `AttributeError`. Das Skript bricht ohne Kontext ab. Fix: `if d is None: return {"error": "no tinyfish doc"}`.

9. **Edge Case** — `replay.py:74` – `removeprefix("ALT:")` ist case-sensitiv. Ein Closing-Satz, der mit `alt:` beginnt, wird nicht erkannt, obwohl `norm()` später kleinschreibt. Fix: case-insensitive prüfen.

10. **Praxis** — `live_check.py:100` – `duration >= 120` hardcoded. Nicht konfigurierbar, obwohl `pace` schon Parameter ist. Fix: als Konstante oder CLI-Parameter exposed.
