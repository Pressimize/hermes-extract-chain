Alle Befunde an ausführbarem Code geprüft (176 Tests grün, `ruff` sauber; Probe-Skript gegen `extract_chain/fetchers.py`).

## Befunde `extract_chain/fetchers.py`

**1. Bug / Robustheit — Firecrawl: `data` und `metadata` werden nicht auf `dict` geprüft → `AttributeError` als „Transportfehler"**
Zeilen 153–154 (`data = payload.get("data") or {}`, `meta = data.get("metadata") or {}`), Fehlerpfad 167.
Konkret: Firecrawl antwortet `200 {"success": true, "data": "..."}`, `{"data": [{"markdown": ...}]}` oder `{"data": {"metadata": "nope"}}`. Dann wirft `.get` auf einem `str`/`list`, der breite `except Exception` meldet `Firecrawl: AttributeError` mit `code="AttributeError"`. Folge: ein kaputter Reply ist in der Logzeile nicht von einem echten Absturz zu unterscheiden (`firecrawl=AttributeError`, kein Code aus der L1-Liste), der eigentliche Fehler verschwindet, und ein Bug im Plugin tarnt sich als Netzwerkfehler.
Fix: `data = payload.get("data"); data = data if isinstance(data, dict) else {}` und ebenso für `meta` → dann greift der vorhandene `malformed`-Pfad wie bei `_json`.

**2. Bug — Firecrawl: 2xx-Antwort ohne `success` schreibt den Antwort-Body in das Fehlerfeld**
Zeilen 150–151: `detail = f"API {response.status_code}: {payload.get('error') or response.text}"`.
Konkret: `200 {"data": {"markdown": "M…", …}}` → `{"error": "Firecrawl: API 200: {\"data\":{\"markdown\":\"MMMM…", "code": "api_200", "status": 200}`. Bis zu 200 Zeichen Seiteninhalt landen im `error` (geht als Eintragsfehler ans Modell und als Pausengrund in K7), und ein Ergebnisfehler trägt `status: 200`. Tritt auf, sobald Firecrawl sein Envelope ändert oder ein Proxy/CDN mit 200 + JSON-Fehler antwortet.
Fix: `response.text` nur verwenden, wenn `_json(response)` leer ist; bei 2xx ohne `success` stattdessen `malformed`, und `status` nur für `>= 300` durchreichen.

**3. Bug — `_redact` ersetzt den Key als Teilzeichenfolge: kurzer Key zerstört TinyFish-Codes und hebt K2 auf**
Zeilen 46–47 (`re.sub(re.escape(form), "[key]", text, flags=re.IGNORECASE)`), Wirkung über 125–128.
Konkret: `TINYFISH_API_KEY=login` → TinyFish meldet `login_required` → Ergebnis `{"error": "TinyFish: [key]_required", "code": "fetch_failed"}`. Damit greift `chain.py:180` (`FINAL_TINYFISH_CODES`) nicht mehr, und jede404-/Login-Seite kostet statt Sofort-Abbruch einen Firecrawl- und einen Keenable-Request (Credits, bis zu +65 s pro URL). Mit Key `e` wird jedes `e` im Fehlertext ersetzt.
Fix: die case-insensitive Teilzeichenfolgen-Ersetzung nur bei `len(key) >= 8` anwenden, sonst nur den exakt geschriebenen Key ersetzen.

**4. Performance — `_redact`/`_error` arbeiten über den ungekürzten Body**
Zeilen 47–48 (`" ".join(text.split())`, zwei `re.sub`-Durchläufe), 53, 151, 184.
Konkret: die im eigenen Test beschriebene 4-MB-Fehlerseite (`tests/test_fetchers.py:269–272`) kostet **0,34 s und 46 MB Spitzenbelastung** für ein210-Zeichen-Ergebnis; dabei existieren Body, `detail`-f-String, zwei `re.sub`-Ergebnisse und die Token-Liste von `text.split()` (Millionen 14-Zeichen-Objekte) gleichzeitig. Bei mehreren gleichzeitigen Extrakten vervielfacht sich das.
Fix: vor der Redaktion großzügig kürzen (z. B. 64 KiB) und danach auf 200 Zeichen, statt `" ".join(text.split())` durch `re.sub(r"\s+", " ", text)` ersetzen (keine Zwischenliste).

**5. Bug — Firecrawl: Truthiness von `success`**
Zeile 150: `not payload.get("success")`.
Konkret: `{"success": "false", "error": "rate limit exceeded", "data": null}` → `"false"` ist truthy → Erfolg mit leerem Inhalt → `classify` = `empty`, die Kette steigt auf Keenable, die eigentliche Meldung geht verloren, Logzeile `firecrawl=empty`.
Fix: `payload.get("success") is not True` (A2 sagt „Success means `success: true`").

**6. Robustheit — D9-Umgehung bei `statusCode` als Zeichenkette**
Zeile 156: `isinstance(status, int)` akzeptiert `bool` (`True` = 1 gilt als 2xx-nah) und lehnt `"404"` ab.
Konkret: `{"success": true, "data": {"markdown": "Z…", "metadata": {"statusCode": "404"}}}` → Prüfung übersprungen, `classify` = `ok` (nachgemessen), die 404-Seite geht als Inhalt ans Modell.
Fix: `int(status)` in `try/except (TypeError, ValueError)` und dann vergleichen.

**7. Edge Case — TinyFish-Einträge ohne `url` landen unter `found[""]` und werden per Redirect-Fallback zugeordnet**
Zeilen 114–115 (`exact[str(name or "")] = found[_slashless(name)] = doc`), 129–130.
Konkret: `{"results": [{"text": "A"}]}` für `["u"]` → `found == {"": doc}`, `len(found) == 1`, `"u" not in found` → Fallback hängt den Eintrag ohne jede URL an `u` (Inhalt „A"). Bei zwei namenlosen Einträgen überlebt nur der letzte.
Fix: in `put` Einträge ohne nicht-leeres `url` überspringen (oder den `""`-Schlüssel vor dem Fallback aus `found` entfernen).

**8. Security (dokumentiert, aber erwähnenswert) — `final_url` landet ungefiltert im Modell-Text**
Zeile 121 (`final_url: item.get("final_url") or item.get("url")`), weiter `chain.py:127` in `NOTE_REDIRECT`.
Konkret: antwortet TinyFish mit `final_url = "https://a.example/?token=SECRET"`, steht das Query-Token (auf 200 Zeichen gekürzt) im Prompt. S7 prüft die Domain, nicht den Query-String.
Fix: wenn schon, Query und Fragment der `final_url` entfernen (Host + Pfad genügen für S7/V10).

**9. Stil / Konsistenz**
Zeilen 51, 63 (`-> dict` ohne Typparameter, während `dict[str, dict]` sonst präzise annotiert ist);106/110/133 derselbe Zweizeiler dreimal; 115 verkettete Zuweisung über zwei Dicts mit verschiedenen Schlüsselsemantiken; 46 Conditional-Expression in der Iterable-Position.
Fix: kleine Helfer `def _all(urls, doc) -> dict[str, dict]`, `exact[str(name)] = doc` und `found[_slashless(name)] = doc` in zwei Zeilen, `key = key if len(key) >= 8 else ""`-Guard für die Redaktion.
