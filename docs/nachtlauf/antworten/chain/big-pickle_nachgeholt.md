**1. Bug** — `extract_chain/chain.py:82-83` (genutzt in `classify`, Zeilen 91/94/102)
`_visible` entfernt nur Tags, nicht den Inhalt von `<script>`/`<style>`. Eingabe: `classify(doc("<script>" + "x"*600 + "</script>"))` → 600 „sichtbare" Zeichen → `"ok"`, obwohl die Seite leer ist; umgekehrt kann Inline-JS mit dem Wort `captcha` unter 1500 Zeichen als `"challenge"` klassifizieren. Vorschlag: `<script…>…</script>`/`<style…>…</style>` (DOTALL) vor dem Tag-Strip entfernen.

**2. Bug** — `extract_chain/chain.py:97` und `99-100` (Folgen 187, 214-215)
Wall-/Paywall-Marker werden am Roh-HTML inkl. Attribute und Tags gematcht, die Längen aber sichtbar gemessen. Eingabe: `doc(ARTICLE + '<script src="/js/cookie-consent.js"></script><a href="/datenschutzeinstellungen">')` (zwei Marker in Markup, Artikel ist normal) → `"wall"` → Zeile 187 überspringt Firecrawl; schlägt Keenable fehl, liefert Zeile 214-215 den echten Artikel mit der Notiz „Consent wall detected". Vorschlag: Marker gegen den getaggten Text prüfen (wie E2/E7), nicht gegen das Roh-HTML.

**3. Edge Case** — `extract_chain/chain.py:94` (Folge 176-177)
Die 1500-Zeichen-Grenze lässt lange Bot-Checks durchrutschen. Eingabe: `classify(doc(BOT + " " + "a"*1600))` → `"ok"` → `run_chain` gibt die Bot-Check-Seite ohne jede Notiz als Ergebnis zurück, das Sprachmodell hält sie für den Artikel. Vorschlag: Marker-Erkennung auch oberhalb der Grenze zulassen (nur als schwächeres Signal) oder `ok`-Rückgabe mit `NOTE_CHECK` versehen, wenn ein Marker vorhanden war.

**4. Edge Case** — `extract_chain/chain.py:133-134`
`finalURL` wird für jeden String gesetzt, auch für relative oder leere Werte. Eingabe: `run_chain(URL, {**doc(ARTICLE), "final_url": "/relative"}, None, None)` → `metadata = {"sourceURL": …, "finalURL": "/relative"}` (die Werte `/relative` und `""` tauchen in `test_no_redirect_note` auf, dort wird aber nur `content` geprüft) – die Website-Policy-Prüfung (S7) bekommt damit keine absolute URL. Vorschlag: nur setzen, wenn `urlsplit(final).scheme in ("http", "https")` und Host vorhanden.

**5. Edge Case** — `extract_chain/chain.py:116-118`
`_redirect` erkennt nur Host-Wechsel oder Wegfall bis auf Root/Locale-Root. Eingabe: angefragt `https://news.example/2024/09/artikel`, final `https://news.example/artikel` → `locale_root` ist False → keine `NOTE_REDIRECT`, obwohl es eine andere Seite ist; der Text wird als von der angefragten URL präsentiert. Vorschlag: beliebige Pfadabweichung melden (www/Scheme/Slash/Query/Fragment weiterhin ignorieren).

**6. Security** — `extract_chain/chain.py:127` (Regel inverse in Kommentar Zeile 143)
Die Notiz schreibt die finale URL roh in den Modell-Text, inklusive Query und Userinfo, nur auf 200 Zeichen gekürzt. Eingabe: `final_url="https://other.example/cb?ticket=abc123"` → Token landet in `content`, während die Logzeile Query-Strings bewusst weglässt. Vorschlag: in der Notiz nur Scheme+Host+Pfad übernehmen (Query/ userinfo streichen).

**7. Performance** — `extract_chain/chain.py:91`, `152`, `197-200`
`_visible` rechnet pro Dokument mehrfach denselben `re.sub` über das volle HTML (classify, `_reason`, Zeilen 197-200 bis zu viermal). Vorschlag: `visible` je Dokument einmal berechnen und durchreichen.

**8. Best Practice** — `extract_chain/chain.py:25-39` (Kompilierung Zeile 69-72)
`WALL`/`PAYWALL`/`CHALLENGE` sind mutable Listen, die Regexe werden einmal beim Import gebaut. `WALL.append("neuer marker")` ändert die exportierte Liste (Tests in `test_chain.py:97-104` lesen sie), `classify` nutzt weiterhin den alten Satz – Tests und Laufzeit auseinander. Vorschlag: als Tuple/Frozenset definieren.
