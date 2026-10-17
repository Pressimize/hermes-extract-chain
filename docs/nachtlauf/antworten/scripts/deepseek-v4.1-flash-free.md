## Befunde (sortiert nach Schwere)

**1. Bug – `replay.py:41-44` (JSON-Fehlerkörper als Nicht-Objekt)**
`json.loads(detail)` kann einen String, eine Zahl oder eine Liste liefern (z. B. wenn Keenable `"some error"` als JSON-String zurückgibt). Dann wirft `body.get(...)` in Zeile 43 `AttributeError`, gefangen wird nur `ValueError` (Z. 44) → Skript bricht ab.
Fix: `if isinstance(body, dict): detail = body.get("message") or body.get("error") or detail` oder `except (ValueError, AttributeError)`.

**2. Bug/Edge – `live_check.py:104` (Host als Dict-Schlüssel kollabiert URLs)**
`by_host` bildet `host -> letzte Logzeile`. Enthält ein `web_extract`-Call zwei URLs desselben Hosts (häufig), überschreibt die zweite die erste. In Z. 108/111 wird dann für *beide* Cases dieselbe (letzte) Zeile verwendet: hat B `keenable=ok` und A nicht, meldet die Prüfung bei A fälschlich „Keenable result without note“, und die gedruckte Anbieterdiagnose ist falsch. Echte Fehler werden so maskiert bzw. erfunden.
Fix: Logzeilen in Reihenfolge den Cases zuordnen (Index/URL), nicht per Host-Dict.

**3. Bug/Edge – `live_check.py:91-93` (ungeprüfter Rückgabewert)**
`json.loads(raw)` wirft `TypeError`, wenn `web_extract_tool` `None`/Nicht-String liefert – nicht gefangen (nur `ValueError, AttributeError`). Zusätzlich würde valides JSON, das kein Objekt ist (z. B. eine Liste), über `AttributeError` in `results=[]` münden und einen Protokollbruch still verschlucken.
Fix: `raw` auf `str` prüfen/`TypeError` fangen und `json.loads`-Ergebnis auf `dict` validieren.

**4. Bug/Edge – `replay.py:78,103,108` (`out["content"]` ohne None-Schutz)**
`out.get("error")` wird erst in Z. 104 geprüft, aber `content` schon vorher in Z. 78/103 (`split`, `splitlines`) und Z. 108 verwendet. Liefert `run_chain` im Fehlerfall `content=None`, gibt es `AttributeError`. Fix: `content = out.get("content") or ""` früh setzen.

**5. Edge Case – `replay.py:59-60` (nur `ast.Assign`)**
`load_dict` erkennt nur `Assign`. Eine annotierte Zuweisung `CLOSING: dict = {...}` ist `ast.AnnAssign` und wird nicht gefunden → `SystemExit` mit irreführender Meldung. Fix: `isinstance(node, (ast.Assign, ast.AnnAssign))`.

**6. Edge Case – `replay.py:70-73` (`sentences` ungeprüft)**
`sentences[0]` wird ohne Längenprüfung indexiert: leere Liste → `IndexError`; ist der Wert versehentlich ein String, prüft `norm(sentences[0])` nur ein einzelnes Zeichen → fast immer „yes“, stille Falschbewertung. Fix: Typ/Länge validieren (`if not isinstance(sentences, list) or not sentences: ...`).

**7. Robustheit – `live_check.py:83` (Append-Modus)**
`open(..., "a")` hängt bei jedem Lauf an dieselbe Datei an; `results.jsonl` sammelt Duplikate/veraltete Zeilen, die Rate-Auswertung (Z. 116-127) betrachtet aber nur den aktuellen Lauf – ein Anbieterlimit über zwei Läufe hinweg fällt nicht auf. Fix: `"w"` oder Zeitstempel im Dateinamen.

**8. Robustheit – `live_check.py:79` (Log-Level-Annahme)**
`setLevel(INFO)` am Root hilft nicht, wenn das Plugin seinen Logger auf `WARNING` o. ä. setzt. Dann bleibt `collect.lines` leer, `by_host` ist leer und sowohl die Keenable-Notiz-Prüfung (Z. 108) als auch die Rate-Prüfung (Z. 119-127) werden still übersprungen („problems: none“). Fix: den Plugin-Logger gezielt auf `INFO` setzen bzw. prüfen, ob überhaupt L1-Zeilen ankamen, und sonst warnen.

**9. Stil/Konfiguration – `live_check.py:27`**
Ohne `HERMES_ROOT` und ohne `LOCALAPPDATA` wird `ROOT="hermes"` (relativ) – der spätere Fehler ist ein unverständlicher `ImportError`/fehlender Pfad statt einer klaren Meldung. Fix: fehlendes `LOCALAPPDATA` auf Nicht-Windows früh mit klarer Meldung abbrechen.
