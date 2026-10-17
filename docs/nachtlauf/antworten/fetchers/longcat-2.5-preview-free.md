## Befunde (fetchers.py)

**1. Robustness — Ziel-Status-Check von Firecrawl lässt alles durch, was kein `int` ist**
Datei: `extract_chain/fetchers.py:155-156`
```python
status = meta.get("statusCode")
if isinstance(status, int) and not (200 <= status < 300 or status == 300 ...):
```
Wenn Firecrawl `success: true` meldet, das Feld `statusCode` aber fehlt (`None`) oder als String (z. B. `"404"`) liefert, gilt die Antwort als Erfolg – der Inhalt einer 403/404/500-Fehlerseite des Zielservers wird als Dokument durchgelassen. Die Fehlererkennung ist hard auf den Typ `int` festgelegt; jeder andere Wert fällt durch.
Vorschlag: `int(status)` parsen (mit `try/except (TypeError, ValueError)`), damit auch stringförmige Statuscodes erkannt werden; `None` bewusst als „kein Ziel-Status" separat behandeln.

**2. Edge Case — URL-Matching ist case-sensitiv, obwohl der Host per RFC 3986 case-insensitiv ist**
Datei: `extract_chain/fetchers.py:78` (Wirksamkeit in `:115`, `:129-135`)
Der Input `https://EXAMPLE.com/seite` wird mit `rstrip("/")` normalisiert, aber nicht lowercased. Wenn TinyFish den Host in seiner Antwort normalisiert (`https://example.com/seite`), schlägt das Matching fehl und die URL erhält `no_result`, obwohl ein Ergebnis vorliegt. Der Single-URL-Fall (`:129-130`) rettet nur dann, wenn genau ein Eintritt existiert; in einem Batch mit mehreren URLs nicht.
Vorschlag: Host beim Vergleich case-insensitiv machen (Host-Teil `.lower()` oder `.casefold()`), Pfad bleibt case-sensitiv.

**3. Performance — Megabyte-große Fehlerseiten werden vollständig in den Fehlertext geladen**
Datei: `extract_chain/fetchers.py:151` (gleiches Muster in `:184`)
```python
detail = f"API {response.status_code}: {payload.get('error') or response.text}"
```
Bei einer WAF-/CDN-Fehlerseite von mehreren MB hält `_redact` (`:43-48`) den komplett eingelesenen `response.text`-String und führt `re.sub` über den ganzen Text aus, obwohl `:53` danach nur 200 Zeichen in den Fehler übernimmt. Der angehängte Test `test_megabyte_error_page_gives_a_short_error` (`tests/test_fetchers.py:269`) zeigt, dass solche Bodies erwartbar sind.
Vorschlag: Text für die Feilmeldung begrenzen (z. B. `response.text[:8192]`) – oder `_redact` so umbauen, dass Redaktion und Truncation auf einem Fenster laufen.

Hinweis: Die `except Exception`-Blöcke (`:131`, `:167`, `:195`) zusammen mit `asyncio.timeout` (`:72`) sind kein Befund – der `async with asyncio.timeout`-Block konvertiert den `CancelledError` beim Verlassen zu `TimeoutException` und damit fangbar (Test `test_deadline`, `tests/test_fetchers.py:150`, deckt genau diesen Pfad ab).
