## Befunde (nach Schwere)

**1. Bug/Performance — `provider.py:138`: httpx-Standard-Timeout von 5 s gilt für alle drei Stufen**
`httpx.AsyncClient(...)` wird ohne `timeout=` gebaut, also5 s für Connect *und* Read. `extract(["https://example.com/artikel"])` mit einem Firecrawl-Scrape, der 8 s braucht, liefert `httpx.ReadTimeout` und damit `"TinyFish: ReadTimeout; Firecrawl: ReadTimeout; Keenable: ReadTimeout"` — obwohl alle drei funktionieren würden. Live-Fetch und JS-Rendering sind genau die Fälle, für die die Kette gebaut ist. Fix: `timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)` (oder je Stufe konfigurierbar).

**2. Bug/Konfiguration — `provider.py:107-108`: `is_available()` prüft nur den TinyFish-Key**
Mit gesetztem `FIRECRAWL_API_KEY`, aber ohne TinyFish-Key meldet der Anbieter `False`, Hermes bietet `web_extract` gar nicht an — obwohl `_chain` (139-140) und `test_missing_tinyfish_key_goes_to_firecrawl` genau diese Konfiguration ausdrücklich unterstützen. Die Degradierung ist im Produktivpfad toter Code. Fix: `any(_env(k) for k in KEYS)` oder TinyFish-Konsequenz durchziehen und den No-Key-Zweig entfernen.

**3. Bug/Robustheit — `provider.py:145-146` + `188-192`: eine kaputte TinyFish-Antwort vernichtet alle URLs**
`_watch` liest ungeschützt `doc["error"]` und `doc["code"]`. Ein Doc mit `status == 402`, aber ohne `code` (z. B. weil `fetchers.tinyfish` eine Fehlervariante nicht kennt) wirft `KeyError` — *außerhalb* von `run_chain`. Der Exception-Handler in `extract` (129-131) macht dann aus allen5 URLs `failure(url, "extract-chain: KeyError")`, auch aus denen, die TinyFish erfolgreich geliefert hat; im Log steht nur `"call failed: KeyError"`. Fix: `doc.get("error", ...)`, `doc.get("code", "http_402")`, `_watch`-Schleife in eigenen `try/except` und/oder `gather(..., return_exceptions=True)` mit Auswertung pro URL.

**4. Bug/Abbruch — `provider.py:124` und `172-173`: `/stop` bricht laufende Anfragen nicht ab**
`is_interrupted()` wird nur *vor* dem TinyFish-Batch und *vor* jeder Stufe geprüft. Läuft der TinyFish-Batch 30 s, wartet der Nutzer nach `/stop` trotzdem, weil nichts gecancelt wird. Fix: die laufenden Tasks (aus `gather`) speichern und bei gesetztem Interrupt-Flag cancellen bzw. vor dem Start von `_chain` nochmals prüfen.

**5. Edge Case — `provider.py:121`: leere Strings passieren die URL-Prüfung**
Nicht-Strings werden abgefangen (`NOT_A_URL`), `" "` oder `""` nicht: `_blocked("")` kann `None` liefern, dann geht `""` als reguläre URL in den TinyFish-Body (`{"urls": [""]}`) und erzeugt einen kryptischen Stage-Fehler statt eines klaren Eintrags. Fix: `if isinstance(url, str) and url.strip()` filtern, sonst `NOT_A_URL`.

**6. Edge Case — `provider.py:121`/`133`: `urls` wird dreimal durchlaufen**
`extract(generator)` funktioniert nicht: `unique` verbraucht den Generator, die Rückgabeliste (133) ist leer — `extract()` liefert `[]` statt eines Eintrags je URL. Fix: `urls = list(urls)` in Zeile 117 (Typannotation bleibt `list[str]`, der Aufruf ist trotzdem abgesichert).

**7. Edge Case — `provider.py:97` und `178-184`: `_paused` wächst unbegrenzt und hält veraltete Pausen**
Einträge werden logisch (z. B. `test_pause_is_dropped_when_the_clock_was_set_back`) nie entfernt, physisch nie. Jeder Schlüsselwechsel (Profilwechsel, rotierter Key) legt einen neuen Digest-Eintrag an; stellt der Nutzer einen alten Key wieder her, greift die alte Pause noch bis zu 24 h. Fix: beim `_paused`-Zugriff abgelaufene Einträge (`until <= now`) poppen.

**8. Best Practice — `provider.py:92-105`: Basisklassen-Vertrag nicht eingehalten**
`__init__` ruft `super().__init__()` nicht auf (Hermes kann dort Zustand/Attribute setzen), und `name`/`display_name` sind Properties: `ExtractChainProvider.name` auf Klassenebene liefert ein `property`-Objekt statt `"extract-chain"`. Sichtbar wird das, sobald Hermes' Registry oder Basisklassen-Methoden Klassenattribute lesen oder im Konstruktor initialisierte Felder nutzen — dann `AttributeError`/`TypeError` schon bei `register()`. Fix: Klassenattribute `name = NAME`, `display_name = "..."`, dazu `super().__init__()`.

**9. Security/Defense in Depth — `provider.py:191`: Provider-Fehlertext wird 24 h gespeichert und erneut ausgegeben**
`_paused` merkt sich `doc["error"]` ungekürzt; jeder spätere Eintrag wiederholt diesen Text (Zeile 184). Dass der Schlüssel nicht landet, beweist nur der Test mit dem `Authorization`-Header (Test 346/373) — jeder andere geheimnisartige Teilstring (Query-Key, E-Mail) bleibt unredigiert und wird über Stunden mehrfach in Modellantworten wiederholt. Fix: Grund auf ~200 Zeichen kürzen und durch dieselbe Redaction schicken wie die übrigen Fehlertexte.

**10. Diagnose — `provider.py:74-76`: Block und Policy-Fehler sind für den Nutzer nicht unterscheidbar**
Bricht der Aufruf der Blocklist (z. B. `TypeError` nach einem Hermes-Update mit geänderter Signatur), blockiert `_blocked` jede URL mit `"Blocked by website policy: the check failed for this URL (TypeError)"`. Der `log.warning` nennt weder die URL noch den Provider, und der Nutzer sieht für *jede* URL eine Blockmeldung, obwohl nichts blockiert ist. Fix: URL und Provider ins Log, die Meldung „extract-chain kann die Blocklist nicht anwenden“ klar von einer echten Blockierung trennen.

Nicht gemeldet, weil bewusst dokumentiert: fehlende Parallelitätsgrenze, keine Retries, neuer Client je Aufruf, `_paused` nur im Speicher, breites `except Exception` an den mit S6 markierten Stellen.
