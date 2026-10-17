Klar. Nur konkrete Befunde aus den angehängten Dateien, nach Schwere sortiert.

### 1. **Sicherheitslücke (Information Leak) – reason aus Provider-Fehler wird ungeprüft gespeichert** 
- **Kategorie:** Security
- **Datei:** `provider.py:191`
- **Zeile:** `self._paused[_slot(provider, key)] = (now + seconds, doc["error"])`
- **Was passiert:** Wenn `doc["error"]` vom Fetcher stammt, wird der komplette Fehlertext als `reason` in `_paused` abgelegt und später in `paused_doc()` (Z. 184) unverändert in den Ausgabetext eingebaut. Fetcher könnten API-Responses oder Header-Teile (z. B. `Firecrawl: API 402: Insufficient credits for Bearer [key]` im Test) enthalten. Obwohl Tests Secrets maskieren, verlässt sich der Provider hier vollständig auf die Fetcher-Sanitierung.
- **Vorschlag:** Nur einen bereinigten, festen Reason (z. B. `f"{provider}: quota exhausted"`) oder eine kodierte Form (`code`) speichern und nie den Rohfehlertext für den gespeicherten Pausen-Grund verwenden.

### 2. **Log-Leak potenziell – Rohfehler in Log** 
- **Kategorie:** Security
- **Datei:** `provider.py:192`
- **Zeile:** `log.warning("extract-chain: %s paused for %d s (%s)", provider, math.ceil(seconds), doc["code"])`
- **Was passiert:** Loggt `doc["code"]` (z. B. `api_402`). Auch hier wird nichts bereinigt. Falls ein Fetcher jemals `code` mit sensitiven Fragmenten füllt, landet es im Log. 
- **Vorschlag:** Nur erlaubte Code-Werte loggen (Whitelist) oder nur den HTTP-Status/Provider-Code ohne Rohfragmente.

### 3. **Bug – Pausenlogik behandelt `left==0` inkonsistent** 
- **Kategorie:** Edge Case / Bug
- **Datei:** `provider.py:182`
- **Zeile:** `if not 0 < left <= DAY:`
- **Was passiert:** `left = until - clock()` ist genau 0 zum Zeitpunkt `until`. Bedingung ist `not (True <= DAY)`? `0 < 0` ist False, also `not (False)` wird True → `paused_doc()` gibt `None` zurück (Pause gilt als abgelaufen/verworfen), statt den noch aktiven Zustand zu behandeln. Typisch bei exaktem Zeitvergleich oder Rundungsfehlern.
- **Vorschlag:** Ersetze durch `if left <= 0: return None` und behandle `left>DAY` separat (z. B. `if left>DAY: return None` für Clock-Backjump), um exaktes `until` nicht zu verlieren.

### 4. **Bug – Website-Policy-Fehler ersetzt Ergebnis ohne Metadaten/Fall-Rückgabe** 
- **Kategorie:** Bug (Datenverlust)
- **Datei:** `provider.py:160–164`
- **Zeile:** `blocked = _blocked(final, entry_url=url) if final and final!=url else None; results[url] = blocked or result`
- **Was passiert:** Wird nach einem Redirect ein Block festgestellt, ersetzt `_blocked()` (Z. 70–88) das komplette Ergebnis durch einen frischen Blockeintrag: `metadata` wird auf `{"sourceURL": entry_url}` gesetzt (Z. 87), alle anderen Metadaten des ursprünglichen Fetcher-Ergebnisses (z. B. `finalURL`, Provider-Metadaten) gehen verloren. Auch für Fehlerfälle, die nach Redirect auftreten, ist das konsistent, aber das überschreibt bewusst das Fetcher-Ergebnis – das ist korrekt, kann aber unbeabsichtigt Kontext entfernen. Kein direkter Fehler, aber konkret beobachtbar.
- **Vorschlag:** Falls Block erkannt wird, übernimm nur Blockfelder und behalte `url`/`finalURL` aus `result["metadata"]`, statt komplett zu ersetzen.

### 5. **Edge Case – `check_website_access` wirft Exception und blockiert hart** 
- **Kategorie:** Edge Case
- **Datei:** `provider.py:73–77`
- **Zeile:** `except Exception as exc: blocked = {"message": f"Blocked by website policy: the check failed for this URL ({type(exc).__name__})"}`
- **Was passiert:** Bei jedem Exception im Policy-Check (z. B. `ValueError` bei kaputter URL) wird der URL-Eintrag als blockiert zurückgegeben (`content==""`, `blocked_by_policy` leer). Das ist absichtlich (Sicherheits-/Fail-closed). Allerdings wird der Exception-Typ offengelegt (`ValueError`) – geringfügige Informationsabgabe. Auch wird kein Retry/Skip versucht.
- **Vorschlag:** Nur generischen Grund loggen, Typ nicht im User-facing `error` (z. B. `Blocked by website policy: check failed`) – oder zumindest vermeiden, interne Typen unnötig sichtbar zu machen.

### 6. **Stil/Inkonsistenz – Manifest vs. Verfügbarkeitslogik** 
- **Kategorie:** Abweichung Best Practices
- **Datei:** `plugin.yaml:13`, `provider.py:108`
- **Zeile:** `requires_env: TINYFISH_API_KEY` (required), `is_available() returns bool(_env("TINYFISH_API_KEY"))`
- **Was passiert:** Manifest kennzeichnet `TINYFISH_API_KEY` als `required`, aber `extract()` funktioniert trotzdem ohne TinyFish-Key (Fallback zu Firecrawl, Test `test_missing_tinyfish_key_goes_to_firecrawl`). `is_available()` wird nur von Hermes genutzt, um Verfügbarkeit anzuzeigen – das spiegelt aber nicht „extract möglich“ wider. Kann zu Verwirrung führen (Tool erscheint als nicht verfügbar, obwohl Fallback funktioniert).
- **Vorschlag:** Klären/angleichen: entweder TinyFish wirklich required (dann Fallback-Logik ohne Key entfernen) oder Manifest anpassen (`required: false` bzw. Beschreibung) und `is_available()` so definieren, dass mindestens ein nachfolgender Key vorhanden ist.

### 7. **Performance – deepcopy pro Original-URL** 
- **Kategorie:** Performance (gering, aber konkret)
- **Datei:** `provider.py:133`
- **Zeile:** `return [copy.deepcopy(done[u]) if isinstance(u,str) else failure(u, NOT_A_URL) for u in urls]`
- **Was passiert:** Für jede Eingabe-URL wird ein `deepcopy` des bereits fertigen Dict-Eintrags erzeugt – auch für Duplikate. Bei wenigen URLs (<=5) vernachlässigbar, aber unnötig. Zudem `deepcopy` von flachen Dicts mit Strings/None ist teurer als `dict(entry)` + Kopie verschachtelter Keys.
- **Vorschlag:** Nur bei echten Duplikaten kopieren oder flache Kopie (`{k:v for k,v in entry.items()}`) statt `deepcopy`.

### 8. **Robustheit – fehlender `code` im Pausen-Doc** 
- **Kategorie:** Edge Case
- **Datei:** `provider.py:184,192`
- **Zeile:** `_paused_doc()` baut Reason mit `doc["error"]`, `_watch()` loggt `doc["code"]`
- **Was passiert:** `paused_doc()` greift nie auf `code` zu, aber `watch()` loggt `doc["code"]`. Falls ein 402-Doc aus irgendeinem Grund keinen `code` hat, wirft `doc["code"]` einen `KeyError` im Logpfad (Z. 192). Da Pause nur bei `status==402` ausgelöst wird, ist das unwahrscheinlich, aber `watch()` prüft nicht auf Existenz.
- **Vorschlag:** `doc.get("code", "paused")` oder `str(doc.get("code",""))` verwenden.

### 9. **Klarheit – Policy-Block-Shape nicht strikt validiert** 
- **Kategorie:** Stil/Robustheit
- **Datei:** `provider.py:79–88`
- **Zeile:** `info = blocked if isinstance(blocked,dict) else {}; ... blocked_by_policy = {k: info.get(k,"") for k in ("host","rule","source")}`
- **Was passiert:** Für nicht-dict-Rückgabe wird nur `message`-Fallback genutzt, `blocked_by_policy` bleibt leer. Test `test_policy_block_of_unexpected_shape_still_blocks` akzeptiert das explizit. Funktional korrekt, aber die leeren Strings erschweren Debugging.
- **Vorschlag:** Nur bekannte Keys kopieren und optionale Warnung loggen, wenn unerwartete Keys vorhanden sind – oder `blocked_by_policy` nur setzen, wenn mindestens ein Key nicht-leer ist.

### 10. **Stil – unnötige Zweideutigkeit im Bedingungsausdruck** 
- **Kategorie:** Schlechter Stil
- **Datei:** `provider.py:182`
- **Zeile:** `if not 0 < left <= DAY:`
- **Was passiert:** Chained Comparison negiert – schwerer lesbar als explizite Prüfung. Keine Funktionsänderung, aber erschwert Review und Fehlersuche (gerade bei Zeitgrenzen).
- **Vorschlag:** `if left <= 0 or left > DAY: return None` schreiben.
