## Befunde (sortiert nach Schwere)

**1. Edge Case – Marker-Halbwelt konsistent**  
`chain.py:94–100`: Challenge sucht nur im sichtbaren Text (`_visible`), Wall/Paywall im Rohtext inkl. Tags und Attribute.  
Eingabe: Firecrawl-Seite mit `<div class="consent">` und `<button class="accept-all">` im Kopfbereich, sichtbarer Artikel danach > 2000 Zeichen im Markup-Vorspann → fälschlich `wall`.  
Vorschlag: Wall/Paywall ebenfalls auf `_visible` (oder `visible[:WALL_WINDOW]`) suchen, analog zu Challenge.

**2. Edge Case – `<`/`>` im Fließtext**  
`chain.py:68`, `83`: `_TAGS = r"<[^>]*>"` schneidet auch echte Textpassagen.  
Eingabe: `"Rechnung: 5 < 10 > 3 und weiter …"` → sichtbare Länge verkürzt, Marker können verschwinden oder Längen-Grenzen (E2/E8) verrutschen.  
Vorschlag: Nur Tag-ähnliche Muster entfernen (z. B. `</?[A-Za-z][^>]*>`) oder bewusst als dokumentierte Heuristik lassen und in der Doku halten.

**3. Bug (Robustheit) – `pdf_pages` ohne Formprüfung**  
`chain.py:124–125`: `pages := doc.get("pdf_pages")` und dann `pages[0]`/`pages[1]`.  
Eingabe: Provider liefert `pdf_pages=30` oder `(30,)` → `IndexError`/`TypeError` im `try` von `run_chain`, S6 fängt es und ersetzt einen brauchbaren Fetch durch `failure(url, "extract-chain: …")`.  
Vorschlag: `isinstance(pages, tuple) and len(pages) == 2` prüfen, sonst Note weglassen.

**4. Edge Case – Redirect ohne Portvergleich**  
`chain.py:111`: Nur `hostname` ohne Port.  
Eingabe: `https://news.example:8443/jobs` → `https://news.example/jobs` ergibt keinen Redirect-Hinweis, obwohl es ein anderer Endpunkt sein kann.  
Vorschlag: `a.port`/`b.port` mit ins Vergleichskriterium nehmen (Default-Ports normalisiert).

**5. Edge Case – 2-Buchstaben-Pfade als Locale**  
`chain.py:73`, `117–118`: `_LOCALE` hält jeden `xx`-Pfad für einen Locale-Root.  
Eingabe: `https://x.example/jobs` → `https://x.example/id/` (Feature-/Artikel-Slug „id“) erzeugt fälschlich `NOTE_REDIRECT`.  
Vorschlag: Nur gängige Locales zulassen oder Host-Wechsel und Locale-Root trennen und im Zweifel kein Note setzen.

**6. Stil – mutable Marker-Listen**  
`chain.py:25–39`: `WALL`/`PAYWALL`/… sind Module-Listen; Laufzeit-`append` würde Klassifikation global ändern, ohne dass der Code es zeigt.  
Vorschlag: `tuple` statt `list` (Compile-Schleifen bleiben unverändert).

**7. Performance – `_visible` mehrfach je Dokument**  
`chain.py:152`, `197–200`: In `classify`, `_reason` und den Thin-Vergleichen wird derselbe Regex-Strip wiederholt.  
Eingabe: Dünne Seiten mit großem Markup → mehrere volle Regex-Läufe je Stufe.  
Vorschlag: `visible` einmal pro `doc` berechnen und durchreichen (z. B. Cache-Key `id(doc)` oder lokales Ergebnis aus `classify`).
