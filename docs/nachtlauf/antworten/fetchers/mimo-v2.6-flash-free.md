**Befunde (nach Schwere)**

1. **Security** — `fetchers.py:46–47, 151`  
   Feuert Firecrawl-Body ohne `error`-Feld als JSON mit escaped Slashes zurück (z. B. Key `fc-a/b`, Roh-Text `..."bad key fc-a\/b"`), wird nur `key` und `quote(key)` ersetzt, nicht `a\/b`. Der Key steht dann in `error`.  
   Fix: zusätzlich JSON-Escaped-Formen redigieren (z. B. `form.replace("/", "\\/")`, `\n` o. ä.) oder nie `response.text` ungefiltert übernehmen.

2. **Performance** — `fetchers.py:45–48, 53, 151, 184`  
   `response.text` (auch mehrere MB) wird vor dem Kürzen auf `ERROR_MAX` komplett redigiert und whitespace-gekollabiert. Auslöser: 502-HTML von Keenable/Firecrawl in Megabyte-Größe.  
   Fix: Body vorher hart kürzen (z. B. `text[:8192]`), dann redact + truncate.

3. **Edge Case** — `fetchers.py:153–154`  
   `payload.get("data") or {}` nur schützt gegen None/leer; truthy Nicht-Dicts (String, Liste) lassen `data.get("metadata")` mit `AttributeError` scheitern → Code `"AttributeError"` statt `"malformed"`.  
   Fix: `if not isinstance(data, dict): return _error("Firecrawl", "malformed reply", "malformed")`.

4. **Edge Case** — `fetchers.py:150, 155–157`  
   `"success": "false"` (String) ist truthy → kein API-Fehler; `"statusCode": "404"` (String) scheitert an `isinstance(status, int)` → 404 wird als Erfolg durchgereicht.  
   Fix: Booleans/Ints strikt prüfen bzw. falschen Typ als `malformed` behandeln.

5. **Bug** — `fetchers.py:124–128`  
   TinyFish-`errors`-Eintrag ohne `url` landet unter `""` und trifft keine Eingabe-URL; bei Batch `["u1","u2"]` bekommen beide nur `no_result`, der eigentliche Code (`bot_blocked`) geht verloren.  
   Fix: bei Einzel-URL-Batch oder fehlendem `url` den Eintrag trotzdem zuordnen oder als Batch-Fehler behandeln.

6. **Bug (Fehlzuordnung)** — `fetchers.py:129–130`  
   Bei genau einer Eingabe-URL und einem Reply-Eintrag wird dieser immer zugeordnet, auch wenn die genannte URL fachfremd ist (nicht nur Redirect). API-Fehler für eine unverwandte URL erscheinen als Ergebnis der angefragten.  
   Fix: nur mappen, wenn Host/Pfad nach Slash-Normalisierung zusammenpassen.

7. **Edge Case** — `fetchers.py:121, 161, 193`  
   `final_url` übernimmt JSON-Werte ungeprüft (None, Zahl, Objekt). Downstream (Policy/Log) kann mit Nicht-Strings brechen.  
   Fix: auf `str` normieren oder `None` belassen und Typ dokumentieren.

8. **Edge Case** — `fetchers.py:184`  
   Keenable-Antwort mit `message` als Dict/Liste ergibt `detail` als Python-`str(dict)` im Fehlertext (unaligned, ggf. lang).  
   Fix: nur Strings durchlassen, sonst `response.text` bzw. `HTTP {status}`.
