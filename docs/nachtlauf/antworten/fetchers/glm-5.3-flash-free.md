**1. Bug/Edge – fetchers.py:150-152**
Firecrawl antwortet HTTP 200 mit `{"success": false, "error": "scrape timeout"}` → Code wird `api_200` und `status: 200` gesetzt. K7 liest `status` als Beleg für einen Anbieter-Fehler; 200 wirkt dort wie Erfolg. Fix: `status` und `api_<n>`-Code nur bei ≥ 300 setzen, sonst z. B. Code `api_failed` ohne Status.

**2. Bug/Edge – fetchers.py:156, 163-164**
`isinstance(status, int)`: (a) `statusCode: true` passiert den Check (bool ist int) → Fehler `target HTTP True`/Code `target_True`; `numPages: true, totalPages: 30` ergibt `pdf_pages (True, 30)`. (b) `'statusCode': "403"` als String überspringt den Target-Check komplett → Erfolg gemeldet, obwohl das Ziel 403 war (D9 umgangen). Fix: int-Koercion (Ziffernstring) zulassen und bool explizit ausschließen.

**3. Edge – fetchers.py:114-130**
Ein Results-/Errors-Eintrag ohne `"url"` landet unter Schlüssel `""` (L115, `str(None or "")`) und kann keinen Input-URL matchen → garantiert `no_result`, obwohl Content existiert; mehrere url-lose Einträge überschreiben sichAdditionally unter `""`. Fix: Einträge ohne URL überspringen statt unter `""` zu registrieren.

**4. Edge – fetchers.py:117-128**
Vorrang Result-vs-Error hängt von der Verarbeitungsreihenfolge ab, nicht von der Reply-Reihenfolge: Results-Schleife läuft immer zuerst, Errors immer danach. Reply `{"errors":[{url:u,...}], "results":[{url:u,...}]}` → Ausgabe `bot_blocked`, obwohl Content existiert. Der Test (test_fetchers.py:137-139) deckt nur die Richtung Results-danach-Errors ab. Fix: bei Konflikt Results bevorzugen oder Verhalten dokumentieren.

**5. Konsistenz/Edge – fetchers.py:121, 161, 193**
`final_url` bleibt roher JSON-Wert, während `title`/`content` mit `str()` gegossen werden: `final_url: 42` oder `[]` landet unverändert im Ergebnis-Dict. Fix: `str(...)`-Cast oder Normalisierung auf None.

**6. Performance – fetchers.py:89-93**
Doppelte URLs über Chunk-Grenzen: 15 URLs mit `https://a.example/x` an Position 3 und 12 → dieselbe URL wird in beiden Chunks angefragt; das spätere Teilergebnis gewinnt stillschweigend. Fix: Eingabe-URLs vor dem Splitten deduplizieren.

**7. Edge – fetchers.py:40, 127**
Cap `{1,40}` in `_CODE`: ein legitimer TinyFish-Code > 40 Zeichen (z. B. `bot_blocked_rate_limit_exceeded_for_this_api_key_today`) fällt in generisches `fetch_failed` → Diagnosewert im L1-Log verloren. Fix: Cap erhöhen (z. B. 64) oder streichen.

**8. Stil – fetchers.py:57-60 (wirkt in 132, 168, 196)**
Transport-Codes sind CameCase-Klassennamen (`ConnectError`, `ReadError`), alle anderen Codes snake_case (`http_429`, `no_result`) → uneinheitlich für Log-Auswertung/Alerting. Fix: Ausnahmen auf snake_case abbilden (`connect_error`).

**9. Tests fehlen – test_fetchers.py:231-249**
Der Keenable-JSON-Fehlerpfad (fetchers.py:184, `message` aus JSON-Body) ist bzgl. Key-Redaktion ungetestet; abgedeckt sind nur Text-Body (257-262) und Authorization-Echo (275-278). Fix: einen Parametrize-Fall `httpx.Response(401, json={"message": "invalid key ke-SECRET"})` ergänzen.
