## Befunde

**1. Potenzielle Bug — `_watch` indiziert `doc["error"]`/`doc["code"]` hart**
`provider.py:191–192`. Liefert ein Fetcher ein Doc `{"status": 402}` ohne `error`/`code` (Fetcher-Änderung, umbenanntes API-Feld), wirft `_watch` KeyError. Bei TinyFish geschieht das in `_chain` außerhalb von `run_chain` (`provider.py:144–146`) → `except` in `provider.py:129–131` ersetzt die Ergebnisse **aller** URLs durch `extract-chain: KeyError`, und es wird keine Pause gesetzt, sodass der Fehler jeden Aufruf wiederholt. Fix: `doc.get("error", "HTTP 402")` bzw. `doc.get("code", "http_402")`.

**2. Potenzielle Bug — `_chain`-Postprocessing verliert die ganze Batch bei einem Ausreißer**
`provider.py:160`: `result["metadata"].get("finalURL")` setzt voraus, dass jedes `run_chain`-Ergebnis `metadata` enthält (aktuell latent, Tests decken nur den Normalfall ab). Trifft das nicht zu, wirft die Zeile nach dem `gather` (147–157, ohne `return_exceptions=True`), und `extract` verwirft über `provider.py:129–131` auch bereits fertig berechnete Ergebnisse der übrigen URLs. Fix: `result.get("metadata", {})` und pro URL ein `try/except` in der Zip-Schleife.

**3. Edge-Case — TinyFish-Pause startet sofort wieder volle ~24 h**
`provider.py:55–57` mit `_watch` (`provider.py:188–191`): Kommt ein 402 kurz NACH 00:05 UTC (Reset hinkt um mehr als die 5-min-Grace; der eigene Testkommentar zu `test_provider.py:420` räumt Verzögerung ein), berechnet `(now-300) % DAY ≈ 60 s` → neue Pause bis 00:05 des Folgetags: ein Versäumnis von Sekunden kostet einen Tag TinyFish. Fix: Liefert TinyFish kurz nach Ablauf der Pause erneut 402, zunächst nur eine kurze Nachlauf-/Retry-Pause statt sofort des vollen Zyklus.

**4. Konsistenz — `is_available` widerspricht dem implementierten No-Key-Failover**
`provider.py:107–108` verlangt `TINYFISH_API_KEY`, während `_chain` den Fall „TinyFish ohne Key → direkt Firecrawl" ausdrücklich bedient (`provider.py:139–144`, getestet in `test_provider.py:124–129`). Mit nur FIRECRAWL/KEENABLE-Key bietet Hermes den Provider nie an; der Codepfad ist nur erreichbar, wenn der Key zur Laufzeit verschwindet. Fix: Gatter auf `any(_env(k) for k in KEYS)` erweitern oder den Pfad im Manifest/Kommentar bewusst als „nur bei Key-Verlust" dokumentieren.

**5. Security/Hygiene — Pause-Reason wird unbegrenzt und ungefiltert persistiert**
`provider.py:191` legt `doc["error"]`Slice unverändert in `_paused` ab; über `_paused_doc` (`provider.py:184`) erscheint der Text später in jeder Notiz (getestet in `test_provider.py:373/380`). Die Schwärzung passiert aktuell nur in den Fetchers (S3) — der Provider hat keine zweite Verteidigungslinie gegen ungeschwärzte oder kilometerlange Fehlertexte. Fix: In `_watch` eine gekürzte (z. B. ≤ 200 Zeichen) Kopie als Reason ablegen.
