Ich habe zusätzlich `extract_chain/chain.py` und `fetchers.py` gelesen, die Design-Entscheidungen in `docs/design.md` geprüft, die Testsuite (181 passed) und `ruff` laufen lassen und den边界-Fall (unten #1) empirisch reproduziert.

## Befunde

**1. Bug — Pausendauer springt bei 00:05:00 UTC von ~0 s auf 24 h**
`provider.py:57` (`_pause_seconds`)
`(now - 300) % 86400` ist um 00:05:00 exakt 0 → `DAY - 0 = 86400`. Verifiziert: 00:04:59 → `paused for 1 s`, 00:05:00 → `paused for 86400 s`, 00:05:01 → `86399 s`.
Das ist genau der Fall, für den der 5-Minuten-Grace (Kommentar S.25, design.md:86) existiert: der Wiederholungsversuch nach der Erneuerung antwortet erneut402 — und sperrt TinyFish dann einen ganzen Tag aus, obwohl das Kontingent evtl. nur wenige Minuten später da ist. `tests/test_provider.py:419` deckt 00:00:02 ab, nicht die Grenze.
Fix: Deckel, z. B. `return min(DAY - (now - TINYFISH_RESET_GRACE) % DAY, DAY - 3600)` für TinyFish; zusätzlich einen Test an der Grenze 00:05:00.

**2. Bug/Edge Case — nicht-serialisierbare Objekte landen im Rückgabe-Eintrag**
`provider.py:133` (und `:120`): `failure(u, NOT_A_URL)` setzt das Eingabeobjekt ungefiltert in `url` und `metadata.sourceURL`. `tests/test_provider.py:272` fixiert das sogar (`{"x": 1}`). Ein `set`, `Path` oder `Decimal` in `urls` (möglich, wenn eine Hermes-Version den geparsten Wert statt des Strings übergibt) ergibt einen Eintrag, den Hermes beim Serialisieren des Tool-Ergebnisses mit `TypeError: Object of type X is not JSON serializable` abweist — der ganze `web_extract`-Aufruf geht verloren statt nur dieses Eintrags.
Fix: `str(u)` (gekürzt) bzw. den Typnamen eintragen; Test entsprechend anpassen.

**3. Robustness — `register()` wirft ungehandelt, wenn die Basisklasse fehlt**
`__init__.py:6` / `provider.py:16`: Für `tools.website_policy` und `tools.interrupt` gibt es jeweils einen `ImportError`-Pfad (S7/S8), für den Basisklassen-Import nicht. `plugin.yaml:8` wirbt `requires_hermes: ">=0.21"` ohne Obergrenze; ist in einer künftigen Hermes-Version das Modul umbenannt oder die Signatur geändert, schlägt `register()` mit `ImportError` im Plugin-Loader fehl und der Nutzer sieht einen Traceback statt „Plugin braucht ein neueres Hermes".
Fix: in `register()` `try/except ImportError` mit klarer Meldung (`RuntimeError("extract-chain braucht Hermes mit agent.web_search_provider")`).

**4. Sicherheit — reservierter Präfix geht bei fremder Block-Form verloren**
`provider.py:85`: `str(info.get("message") or "Blocked by website policy")` reicht eine fremde Message 1:1 durch. Liefert ein Hermes `{"message": "blocked"}` (exakt der Fall im eigenen Test `test_provider.py:182`), lautet der Fehler `"blocked"` — die in `provider.py:33` und design.md:52 dokumentierte Erkennungsphrase für Hermes' keyless rescue fehlt, und `blocked_by_policy` (`:86`) bleibt komplett leer. Sind *alle* URLs eines Aufrufs blockiert, greift der Rescue (design.md:7) und holt die blockierten URLs anonym. Nur `web.keyless_rescue: false` (I2) verhindert das heute.
Fix: Präfix immer setzen (`f"Blocked by website policy: {message}"`) und im Test für *alle* Formen prüfen.

**5. Edge Case — Verweigerungs-Einträge ohne `blocked_by_policy`**
`provider.py:120` (gegen `:86`): Der Fall „Policy-Modul nicht importierbar“ erzeugt Einträge über `failure()`, also ohne den Schlüssel, den die übrigen Blockeinträge tragen. Gerade im Zustand ohne Blockliste sind die Einträge damit die einzigen, die eine externe Erkennung per Schlüssel nicht sicherstellen können.
Fix: `blocked_by_policy: {"host": "", "rule": "extract-chain", "source": "plugin"}` in den Verweigerungs-Eintrag aufnehmen.

**6. Best Practice — `is_interrupted`-Fallback bleibt still**
`provider.py:42-45`: Fehlt `tools.interrupt` (Rename/Update), gilt dauerhaft `False` — `/stop` beendet die Kette nicht mehr, Firecrawl/Keenable Credits werden weiter verbraucht, **ohne eine einzige Logzeile**. S7/D15 behandeln dieselbe Art von Versionsbruch genau umgekehrt (laut, fail-closed).
Fix: einmalige Warnung bei der ersten Nutzung (`log.warning("extract-chain: tools.interrupt nicht importierbar; /stop bricht die Kette nicht ab")`).

**7. Performance — `deepcopy` jedes Eintrags, auch ohne Duplikat**
`provider.py:133`: Bei den üblichen 5 URLs wird der komplette Inhalt (bis ~1 MB pro Artikel) kopiert, obwohl `done[u]` ohnehin exklusiv ist. Kopiert werden müsste nur, wenn dieselbe URL mehrfach vorkommt.
Fix: `copy.deepcopy(...) if urls.count(u) > 1 else done[u]`.

**8. Stil/Wartbarkeit — Providernamen als Stringliterale, Kleinschreibung würde stillschweigend wirken**
`provider.py:57` vergleicht exakt `"TinyFish"`; dieselben drei Namen stehen als Literale in `:140`, `:141`, `:146`, `:152`, `:153`. Ein Tippfehler („tinyfish“) erzeugt einen zweiten Pausenslot und — wegen `provider == "TinyFish"` — eine 24-h-Pause statt der Kurzpause; der Fehler fällt erst im Verhalten auf.
Fix: drei Konstanten (`TINYFISH = "TinyFish"` …) oder eine kleine Enum als Schlüssel für `_slot`/`_pause_seconds` verwenden.
