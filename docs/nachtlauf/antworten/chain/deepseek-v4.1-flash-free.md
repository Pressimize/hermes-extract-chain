## Befunde zu `extract_chain/chain.py`

**1. Performance/DoS – katastrophales Backtracking in `_TAGS` (Zeile 68), genutzt in `_visible` (Z. 83) – HOCH**
`re.compile(r"<[^>]*>")` ist auf Inhalten mit vielen `<` und keinem `>` quadratisch. Gemessen: `"a<"*40000` (80 kB) → 1,7 s, `"a<"*80000` (160 kB) → 6,8 s (vervierfacht sich mit der Größe); hochgerechnet auf 1 MB mehrere Minuten. Der Inhalt ist angreiferkontrolliert (jede abgerufene Seite), `_visible` läuft synchron im Event-Loop und ist damit auch nicht per `asyncio`-Timeout abbrechbar – eine einzige Seite blockiert alle URLs des Aufrufs (Z1 = 120 s).
Fix: `re.compile(r"</?[A-Za-z][^<>]*?>")` (oder `[^<>]*` statt `[^>]*`), besser ein HTML-Parser.

**2. Edge Case/Bug – `_visible` zählt `<script>`/`<style>`-Inhalte als sichtbaren Text (Z. 82-83) – HOCH**
E2/E7/E8 sollen sichtbaren Text messen, `_TAGS` entfernt aber nur die Tags, nicht die Skript-/Style-Bodies. Beispiel einer echten Cloudflare-Bot-Check-Seite: `<script>` + `"var t=...;"*60` + `Just a moment... checking your browser` → 3158 sichtbare Zeichen ⇒ E7-Kappe (1500) greift nicht ⇒ `classify` liefert `ok` statt `challenge`. Ebenso: leeres `<body>` mit großem `<style>`-Block → 1560 Zeichen → `ok` statt `empty`.
Fix: `<script>`/`<style>` samt Inhalt vor der Längenmessung entfernen (oder HTML-zu-Text-Parser).

**3. Edge Case – HTML-Entities werden nicht aufgelöst (Z. 91/83) – MITTEL**
`_visible` macht kein `html.unescape`. `"&nbsp;"*4` (leere Seite) ergibt 24 „sichtbare" Zeichen ⇒ `thin` statt `empty` und damit einen unnötigen Firecrawl-Request; bei 3 Entities (18) ist es korrekt `empty`. Fix: `html.unescape(...)` vor `.strip()`.

**4. Edge Case – Text zwischen einem einzelnen `<` und einem späteren `>` verschwindet (Z. 83) – MITTEL**
Ein realer 680-Zeichen-Artikel mit „a < b … c > d" wird auf 31 sichtbare Zeichen reduziert (Regex frisst alles zwischen `<` und `>`) ⇒ `thin`, obwohl der Text vollständig ist → überflüssiger zweiter Fetch (V9). Fix wie 1 (`</?[A-Za-z]…>`), damit ein bloßes `< ` kein Tag ist.

**5. Security/Konsistenz – `NOTE_REDIRECT` bettet die volle `final_url` inhaltlich ein (Z. 127-128) – NIEDRIG**
`_host` (Z. 143) vermeidet bewusst volle URLs in Logs, „weil Query-Strings Tokens enthalten können". Die Redirect-Notiz gibt aber `final_url` inkl. Query an das Modell und (über Hermes-Cache) weiter. Bei `https://site/login?token=…` landet das Token im Ergebnis. Fix: Query/Fragment (und Userinfo) vor der Ausgabe entfernen.

**6. Robustheit – ungeprüfter Dict-Zugriff `_KIND_TEXT[kind]` (Z. 153) – NIEDRIG**
Kommt ein neuer `classify`-Wert hinzu, der nicht in `_KIND_TEXT` steht, wirft `_reason` `KeyError`; der äußere Handler (Z. 219) macht daraus still ein generisches `extract-chain: KeyError` für die URL statt eines aussagekräftigen Grundes. Fix: `_KIND_TEXT.get(kind, kind)`.

**7. Testlücke – E6-Invariante für Regex-Marker ungeprüft (`tests/test_chain.py:103`) – NIEDRIG**
Der Filter `set(m) & set("\\[](|?+")` schließt genau die Marker aus, für die die Invariante relevant ist (`(?<!cookie-)zustimmung`, `(?<!\w)z\+`/`f\+`). Der Test ist an dieser Stelle vakuant. Fix: die Lookbehind-/Escaped-Marker gezielt in konkreten Paaren prüfen.

**8. Performance – `_visible` wird pro URL mehrfach neu berechnet (Z. 91, 152, 197-202) – NIEDRIG**
`classify` und `_reason` sowie die Thin-Zweige strippen den (potenziell großen) Text jeweils erneut; in Kombination mit Befund 1 multipliziert das die CPU-Last. Fix: die Länge im `doc`/als Rückgabewert einmal berechnen und weiterreichen.

Hinweis: Die bewusst getroffenen Entscheidungen (breites `except`, feste Reihenfolge, Marker-Heuristiken, kein Retry/keine Nebenläufigkeitsgrenze) habe ich nicht als Befund gewertet. Befunde 1–3 sind reproduzierbar; 5–8 sind geringe Schwere.
