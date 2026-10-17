Ich habe provider.py samt Tests gelesen und die Pause-, Policy- und Interrupt-Logik gegen `docs/design.md` geprüft. Die meisten Punkte, die wie Bugs aussehen (breites `except`, `is_available` nur auf TinyFish, keine Concurrency-Grenze, keine SSRF-Prüfung, Pausen nur im Speicher), sind in `design.md` als Entscheidung dokumentiert und daher hier nicht gemeldet. Die Tests (181) laufen grün.

Befunde, nach Schwere:

**1. Edge Case / S5-Verletzung — mehrfache Iteration über `urls`**
`extract_chain/provider.py:121` und `:133`
`urls` wird zweimal durchlaufen (Zeile 121 für `unique`, Zeile 133 für die Ergebnisliste). Bei einem Iterator statt einer Liste ist er nach Zeile 121 erschöpft:
`provider.extract(iter(["https://a.example/"]))` → `[]` (verifiziert), obwohl S5 genau einen Eintrag je Eingabe-URL fordert. Hermes übergibt derzeit Listen, daher nur latent.
Fix: am Anfang `urls = list(urls)` materialisieren.

**2. Security/Lücke in S7 — End-URL-Policy wird bei fehlender `final_url` übersprungen**
`extract_chain/provider.py:160-162` (i.V.m. `chain.py:134-135`)
`final` kommt aus `metadata["finalURL"]`; dieses Feld setzt `chain.py` nur, wenn der Anbieter eine `final_url` vom Typ `str` liefert (z. B. Firecrawl, wenn `data.metadata.url`/`sourceURL` fehlt, s. `fetchers.py:163`). Dann ist `final` falsy und `_blocked(final)` wird nie gerufen: Hat der Dienst serverseitig auf einen blockierten Host weitergeleitet, kommt der Text ohne Blocklist-Prüfung (und ohne V10-Notiz) zurück. Die Vorabprüfung greift nur für die Eingabe-URL.
Fix: mindestens eine Warnung protokollieren, wenn die End-URL unbekannt ist; oder in den Fetchern `final_url` immer befüllen (Rückfall auf die bereits geprüfte Eingabe-URL).

**3. Edge Case — Anzeige-Grenze in `_left` nicht monoton**
`extract_chain/provider.py:67`
`seconds > 3600` schickt genau 3600 s in den Minuten-Zweig: Ein TinyFish-402 um 23:05 UTC ergibt 3600 s → „60 min", 3601 s dagegen → „2 h". K7/A4 verlangen „unter einer Stunde" in Minuten, also müsste 3600 s als „1 h" erscheinen.
Fix: `if seconds >= 3600`.

**4. Robustheit / Konsistenz — `_watch` liest `doc["error"]`/`doc["code"]` ungeschützt**
`extract_chain/provider.py:191-192`, Aufruf im TinyFish-Loop `:145-146`
Anderswo wird `.get` benutzt; hier nicht. Der TinyFish-Loop liegt außerhalb der per-URL-Absicherung (`run_chain`), daher macht ein 402-Doc ohne `error`/`code` die ganze Anfrage zu `extract-chain: KeyError` statt nur eine URL. Mit den heutigen `fetchers` sind die Felder immer gesetzt, also derzeit nicht auslösbar — aber die Struktur bricht S6, sobald ein Fehler-Doc diese Felder nicht mehr garantiert.
Fix: `doc.get("error", "quota used up")` / `doc.get("code", "")`.

**5. Robustheit / S6 — `done[u]` außerhalb des try-Blocks**
`extract_chain/provider.py:133`
Zeile 133 ist nicht durch das `try/except` (Zeilen 127-131) gedeckt. Die Invariante „`done` enthält jeden String aus `urls`" hängt heute nur daran, dass `_chain` via `zip(..., strict=True)` liefert und `run_chain` nie wirft. Kommt dort je eine Lücke hinzu, fliegt ein `KeyError` aus `extract` heraus und Hermes meldet einen Plugin-Bug für den ganzen Aufruf statt eines Fehlers je URL.
Fix: `done.get(u) or failure(u, f"extract-chain: {type(exc).__name__}")`.

Abgelehnt: `is_available()` nur auf `TINYFISH_API_KEY` (design S2/K1, bewusst), Pause 402 pro Provider+Key (K7), final-URL-Check nur bei Abweichung (V10/S7), `copy.deepcopy` je Duplikat (S5).
