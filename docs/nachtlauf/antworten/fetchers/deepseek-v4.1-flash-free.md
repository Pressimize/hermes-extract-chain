Nach Prüfung der beiden angehängten Dateien, sortiert nach Schwere:

**1. Edge Case / Korrektheit – TinyFish bindet fremde Einzelantwort an die angefragte URL**
`fetchers.py:129-130`. Bei genau einer Eingabe-URL wird jede einzelne Antwort, deren `_slashless`-Form nicht exakt passt, umgebogen auf die Eingabe. Beispiel: `tinyfish(client, ["http://a.example/x"], ...)` mit Reply `{"results":[{"url":"http://b.example/y","text":"fremd"}]}` liefert den Text von `b.example` als Ergebnis für `a.example`. Das ist nur als Redirect-Heuristik gedacht, greift aber auch bei einer schlicht anderen vom Dienst genannten URL. Vorschlag: Fallback nur für `errors`-Einträge oder nur bei gleichem Host/Schema anwenden.

**2. Bug – Firecrawl: Nicht-Dict `data`/`metadata` erzeugt `AttributeError` als Code**
`fetchers.py:153-154`. `data = payload.get("data") or {}` – bei einer nicht-leeren Liste bleibt die Liste stehen, `data.get("metadata")` wirft `AttributeError`, der breite `except` macht daraus `{"error":"Firecrawl: AttributeError","code":"AttributeError"}`. Auslöser: `{"success": true, "data": ["x"]}`. Das leakt den internen Klassennamen und ist inkonsistent zu `"malformed"` bei TinyFish/Keenable. Vorschlag: `if not isinstance(data, dict)` bzw. `isinstance(meta, dict)`, sonst `_error(..., "malformed")`.

**3. Edge Case – Firecrawl: 2xx mit ungültigem Body wird als `api_200` gemeldet, samt ganzem Body**
`fetchers.py:150-152`. `httpx.Response(200, json=["x"])` → `_json` liefert `{}` → `not payload.get("success")` greift → Detail `API 200: ["x"]` (ganzer Body) und Code `api_200`, obwohl es eine 200er-Antwort ohne gültiges Format ist. Vorschlag: erst `payload`-Typ prüfen und `"malformed"` zurückgeben, und den Body nicht ungekürzt in den Fehler übernehmen.

**4. Edge Case / Performance – `tinyfish` mit leerer URL-Liste sendet trotzdem eine Anfrage**
`fetchers.py:89`. `len([]) > 10` ist falsch, also läuft `_request` mit `json={"urls": []}` und kann Quota verbrauchen bzw. einen 4xx erzeugen. Vorschlag: `if not urls: return {}` vor dem Request.

**5. Performance / Speicher – `_redact` materialisiert bei großen Fehlertexten die komplette Tokenliste**
`fetchers.py:43-48` (Aufrufe u.a. `151`, `184`). `" ".join(text.split())` baut für den mehr-MB-Body aus `test_megabyte_error_page_gives_a_short_error` eine riesige Liste, bevor auf 200 Zeichen gekürzt wird. Da der Key auch am Textende stehen kann, muss zwar der ganze Text gescannt werden, aber ohne Tokenliste: z. B. `re.sub(r"\s+", " ", text).strip()`.
