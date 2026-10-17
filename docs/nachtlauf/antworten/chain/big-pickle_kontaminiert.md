## Befunde zu `extract_chain/chain.py` (angehängte Fassung)

**1. Kategorie: Bug/Security (DoS) — `_TAGS` frisst Text als Tag und backtrackt quadratisch**
`chain.py:68` (`_TAGS = re.compile(r"<[^>]*>")`), genutzt in `chain.py:83`/`92`.
`<[^>]*>` behandelt *jeden* Bereich von `<` bis zum nächsten `>` als Tag. Eingabe `doc("a < b ... c > d")`: der Bereich `< b ... c >` wird entfernt, sichtbar bleibt `a d` → falsche `thin`/`empty`-Einstufung und unnötiger Zweit-Fetch. Zusätzlich läuft `[^>]*` bei Eingaben mit vielen `<` und keinem `>` bis zum Stringende und muss zurücklaufen: `"a<b " * 80_000` ist O(n²) (gemessen ~13 s vor dem Fix). Da `classify` synchron im Event-Loop läuft, blockiert eine einzige große Seite alle parallelen URLs des Aufrufs.
Fix: nur echte Tag-Anfänge erkennen, z. B. `re.compile(r"</?[a-z][^<>]*>", re.IGNORECASE)`.

**2. Kategorie: Bug (Edge Case) — `<script>`/`<style>`-Inhalte zählen als sichtbarer Text**
`chain.py:68`/`83`.
`_visible` entfernt nur Tags, nicht die Skriptkörper. `doc("<head><script>" + "x"*1600 + "</script></head><body></body></html>")` ergibt ~1600 sichtbare Zeichen → `classify` liefert `ok` statt `empty`. Bei einer Bot-Check-Seite mit viel Inline-JS bleibt `len(visible) >= CHALLENGE_BELOW` und der Marker wird nie geprüft → `ok`/`challenge` verschluckt.
Fix: `<script>…</script>` und `<style>…</style>` (samt Inhalt) vor der Längenmessung entfernen.

**3. Kategorie: Bug (Edge Case) — Wall/Paywall werden im ROH-HTML gesucht; falsche Wall überspringt Firecrawl**
`chain.py:97-101` prüft `text` (mit Tags), während `chain.py:92-95` `visible` nutzt. `chain.py:185`/`188`: bei `kind=="wall"` wird Firecrawl komplett übersprungen.
Seite mit Consent-Markern schon im Markup, z. B. `<script>var t="datenschutzeinstellungen"</script><button>Alle akzeptieren</button>` bei einem sonst vollen Artikel (< 4000 Rohzeichen): zwei Treffer → `wall`, Firecrawl wird nicht gefragt, und wenn Keenable scheitert, bekommt der Aufrufer den Artikel mit `NOTE_WALL` („Consent wall detected").
Fix: Wall/Paywall ebenfalls gegen `visible` (Textkörper) prüfen.

**4. Kategorie: Bug (Robustheit) — ungeprüftes `pdf_pages`/`content` wirft die geholte Seite weg**
`chain.py:125-126`: `if pages := doc.get("pdf_pages"): ... pages[0], pages[1]`. Liefert ein Provider z. B. `{"pdf_pages": 30}` oder eine 3er-Liste, wirft `pages[0]` `TypeError`. Das passiert in `_result` innerhalb von `run_chain`, fällt in `chain.py:220` und ersetzt eine erfolgreich geholte Seite durch `failure(...)` — der Inhalt ist verloren. Analog: `content` ist eine Liste/Dict (kein `str`) → `_TAGS.sub` in `chain.py:83` wirft.
Fix: Typ/Länge prüfen (`isinstance(pages, (tuple, list)) and len(pages) == 2`, `isinstance(content, str)`) und Notizbildung absichern.

**5. Kategorie: Security — `NOTE_REDIRECT` schreibt die volle final-URL (inkl. Query/Token) in den Content**
`chain.py:127-129` normalisiert nur Whitespace, entfernt aber Query/Fragment nicht. `_host` vermeidet bewusst genau deshalb die volle URL (`chain.py:143-144`).
Bei einer Cross-Host-Weiterleitung auf einen Share/SSO-Link, z. B. `final_url="https://other.example/x?token=abc"`, steht das Token danach im Modellkontext, im Hermes-Ergebnis und in der nächsten Log-Stufe.
Fix: in der Notiz nur `scheme://host/path` ausgeben.

**6. Kategorie: Bug (Edge Case) — Challenge-Marker schon bei einem Treffer < 1500 Zeichen → falsche `NOTE_CHECK`**
`chain.py:94-95` (`_hits(...) >= 1`), Ergebnis in `chain.py:217-218`.
Echter Kurzartikel `< 1500 sichtbare Zeichen`, der „captcha" oder „just a moment" nur erwähnt, wird `challenge`. Scheitern Firecrawl und Keenable, wird er mit `NOTE_CHECK` („This looks like a bot-check page") als Bot-Check ausgegeben — aktiv falsche Herkunftsangabe.
Fix: mindestens zwei Marker verlangen (analog Wall/Paywall) oder das Fenster stark verkürzen.

**7. Kategorie: Bug (Edge Case) — `_redirect` meldet normale Fälle als Weiterleitung**
`chain.py:111`/`116-118`. (a) Jeder Host-Unterschied zählt: `example.com` → `example.com.br` oder `news.example` → `m.news.example` erzeugt `NOTE_REDIRECT`, obwohl es dieselbe Seite ist. (b) `_LOCALE` erkennt jedes zweibuchstabige Segment: `/jobs` → `/in/` oder `/it/` gilt als Locale-Root, obwohl das normale Rubriken sind.
Fix: Host-Normalisierung (z. B. `m.` abziehen) bzw. Locale-Whitelist (`de,en,fr,es,it,nl,pl,…`).

**7b. Kategorie: Bug — gemischte Längengrenzen (roh vs. sichtbar)**
`chain.py:96-100`: `short = len(text) < WHOLE_BELOW` nutzt Rohzeichen, die anderen Grenzen sichtbare Zeichen. Eine tagreiche Seite mit 500 sichtbaren und >4000 Rohzeichen gilt als „lang", wird nur im ersten `text[:2000]` geprüft (der im `<head>` liegt), Paywall-Marker im Artikel bleiben unentdeckt. Widerspricht dem Kommentar „shorter texts are checked completely".
Fix: auch `WHOLE_BELOW`/`WALL_WINDOW` auf `visible` beziehen.

**8. Kategorie: Edge Case — HTML-Entities werden nicht aufgelöst**
`chain.py:83` (`_TAGS.sub("", ...)` ohne `html.unescape`).
`doc("&amp;" * 100)` ergibt 500 „sichtbare" Zeichen → `classify` liefert `ok`, obwohl die Seite inhaltlich leer ist. Umgekehrt: `doc("&nbsp;" * 4)` (24 Zeichen) gilt als `thin` statt `empty` und löst einen unnötigen Firecrawl-Fetch aus.
Fix: `html.unescape` vor der Messung.

**9. Kategorie: Performance — `_visible` wird pro URL mehrfach über den vollen Content gerechnet**
Neben `chain.py:92` (in `classify`) weitere volle Regex-`sub`-Läufe in `chain.py:153` (`_reason`), `chain.py:199-201` (K3-Vergleich) und den `NOTE_THIN*`-Aufrufen — bei bis zu fünf URLs pro Aufruf und großen Seiten unnötig. Zusammen mit Befund 1 verstärkt das die Last.
Fix: die sichtbare Länge einmal berechnen und durch `_reason`/Längenvergleiche weiterreichen.

Hinweis: Ich habe die als bewusst dokumentierten Punkte (keine eigene Parallelitäts-/Längenbegrenzung, breite `except`, keine Konfiguration, deutsche Heuristik-Marker, keine SSRF-Prüfung) nicht als Befund gewertet.
