Ich habe die Datei aufgerufen. Hier sind die Befunde, nach Schwere sortiert:

## 1. Wall-/Paywall-Marker werden im Roh-HTML statt im sichtbaren Text gesucht — Falschklassifikation „wall"
**Kategorie:** Bug / False Positive
**Zeile:** `chain.py:97` und `chain.py:99-100` (`text` bzw. `area` gegen `visible`)
**Was passiert:** `EMPTY_BELOW`, `CHALLENGE_BELOW`, `THIN_BELOW` messen `visible`, Wall und Paywall dagegen das volle Markup (inkl. `<head>`, Attribute, Kommentare). Unter4000 Roh-Zeichen wird der komplette Quelltext durchsucht. Eine deutsche Seite mit Consent-Plugin erzeugt im `<head>`/HTML-Kommentar problemlos zwei Treffer: `<script id="consent-manager">` + `<!-- Datenschutzeinstellungen -->`, dazu Text wie `Einwilligung speichern` im Markup. Ergebnis: `kind == "wall"`, `chain.py:184` setzt `wall_page`, `chain.py:187` **überspringt Firecrawl komplett**, und wenn Keenable dann auch scheitert, bekommt der Aufrufer den Artikel mit `NOTE_WALL` („Consent wall detected"). Umgekehrt (Gegenrichtung): bei markup-schweren Seiten mit >4000 Roh-Zeilen liegt `text[:WALL_WINDOW]` komplett im `<head>` — die sichtbare Consent-Wall wird nie gefunden.
**Fix:** Wall und Paywall ebenfalls gegen `visible` suchen (ggf. nur den Textkörper, nicht die Attribute); für `full_page` zusätzlich `WALL_WINDOW` auf der Basis von `visible` anwenden.

## 2. Bot-Check braucht nur *einen* Marker bei bis zu 1500 Zeichen
**Kategorie:** Bug / False Positive
**Zeile:** `chain.py:94`
**Was passiert:** `_hits(_CHALLENGE_RX, visible)` >= 1 genügt, und nur bis 1500 sichtbare Zeichen. Ein 1200-Zeichen-Artikel über Phishing/CAPTCHAs („Ich bin kein Roboter, ich schreibe diesen Text …", „captcha", „just a moment" als Zitat) wird als `challenge` eingestuft. Firecrawl wird dann zwar versucht, aber wenn dessen Ergebnis ebenfalls fehlschlägt, liefert `chain.py:216-217` genau diesen Artikel mit `NOTE_CHECK` („This looks like a bot-check page") — eine aktiv falsche Aussage über die Herkunft. Der Test `test_chain.py:83` deckt nur den Fall >1500 Zeichen ab.
**Fix:** Mindestens zwei Marker verlangen (analog zu Wall/Paywall) oder eine deutlich unauffällige Teilmenge allein als Bot-Check-Definition nutzen und das Fenster auf ~800 Zeichen verkürzen.

## 3. `_visible` entfernt keine `script`/`style`/Kommentar-Inhalte
**Kategorie:** Bug
**Zeile:** `chain.py:68` (`_TAGS`) und `chain.py:82-83`
**Was passiert:** `<[^>]*>` entfernt nur die Tags selbst. Der Text *zwischen* `<script>` und `</script>` bleibt sichtbar. Eine JS-Shell mit 600 Zeichen Inline-Skript plus `<body>Loading</body>` ergibt ~613 „sichtbare" Zeichen → `classify` liefert `ok` statt `thin`/`empty`, und die `empty`-Grenze (20 Zeichen) wird ebenfalls umgangen. Zusätzlich liefert Skript-Quellcode Marker-Treffer für Wall/Paywall (z. B. `consentManager`, `paywall` als Konstante) — dieselbe Ursache wie Befund 1.
**Fix:** Vor `_TAGS.sub` die Blöcke `(?is)<(script|style|template)\b.*?</\1>` und `<!--.*?-->` entfernen (oder mit `html.parser`/`HTMLParser` nur den sichtbaren Text extrahieren).

## 4. Ein Fehler in `_result` vernichtet eine erfolgreich geholte Seite
**Kategorie:** Robustheit / Bug
**Zeile:** `chain.py:124-125`, Auswirkung über `chain.py:219`
**Was passiert:** `final_url` wird defensiv behandelt (`chain.py:133` prüft `isinstance(..., str)`), `pdf_pages` dagegen nicht: `{**doc, "pdf_pages": 30}` (ein Provider, der eine Zahl statt eines Tupels liefert) führt in `pages[0]` zu einem `TypeError`. Die Exception fällt in den äußeren `except Exception` (`chain.py:219`) und liefert `failure(...)` — der Inhalt wird weggeworfen, obwohl die Seite geholt wurde. Dasselbe gilt, wenn `content` kein `str` ist (`chain.py:83`, `_TAGS.sub`).
**Fix:** Beide Felder typprüfen/koerzieren (`isinstance(pages, (tuple, list)) and len(pages) == 2`, `isinstance(content, str)`), und die Notizbildung aus dem try-Block herausziehen bzw. als eigenen try-Schritt absichern.

## 5. Ungekürzte Fremdstrings landen im Content — Token-Leak über Query-Strings, kaputte Notizzeilen
**Kategorie:** Security / Konsistenz
**Zeile:** `chain.py:127` (Redirect-URL) und `chain.py:150-153` (`doc["error"]`)
**Was passiert:** Die Log-Zeile verzichtet bewusst auf die volle URL, weil Query-Strings Tokens enthalten können (`chain.py:143`). Der Text-Pfad tut genau das Gegenteil: `NOTE_REDIRECT` schreibt die vollständige `final_url` (inkl. `?s=<Signatur>` bzw. `?session=…` von SSO-/Share-Links) bis 200 Zeichen in den Content — also in den Modellkontext, in Hermes' Ergebnisse und in die nächste Log-Stufe. Ungeschnitten und ohne Zeilen-Normalisierung ist außerdem der Provider-Fehlertext: `doc["error"]` landet über `_reason` direkt in `NOTE_FIRECRAWL`/`NOTE_KEENABLE`/`NOTE_WALL`/`NOTE_CHECK`. Ein mehrzeiliger Fehlertext (z. B. HTML-Fehlerseite im Body) zerreißt das Ein-Notiz-pro-Zeile-Format, das V1 für die URL vorsieht, und kann scheinbar eigene `[extract-chain]`-Zeilen fälschen.
**Fix:** In der Notiz nur `scheme://host/path` (ohne Query/Fragment) ausgeben; Fehlertexte auf eine Zeile normalisieren (`" ".join(err.split())`) und auf z. B. 200 Zeichen kürzen.

## 6. `_redirect` meldet normale Weiterleitungen fälschlich**Kategorie:** Bug / False Positive
**Zeile:** `chain.py:111` und `chain.py:116-118`
**Was passiert:** (a) Jeder Host-Unterschied gilt als Redirect: `https://m.example.com/jobs` → `https://example.com/jobs` (mobil → Desktop) oder `example.com` → `example.com.br` erzeugen eine Weiterleitungsnotiz, obwohl es dieselbe Seite ist. (b) `_LOCALE.fullmatch` erkennt *jedes* zweibuchstabige Pfadsegment als Locale: `https://example.com/jobs` → `https://example.com/in/` gilt als Locale-Root, obwohl `/in/` eine ganz normale Rubrik sein kann (auch `it`, `at`, `id`). Beide Fälle legen eine irreführende Herkunftszeile über den Text.
**Fix:** Host-Vergleich auf `removeprefix("m.")` erweitern bzw. nur echte Subdomain-/TLD-Wechsel zählen; Locale-Erkennung auf eine Whitelist (`de`, `en`, `fr`, `es`, `it`, `ru`, `pt`, `nl`, `pl`, `tr`, `ja`, `zh`) begrenzen.

## 7. Roh-Text-Längen gegen sichtbare Textlängen gemischt
**Kategorie:** Bug / Lesbarkeit
**Zeile:** `chain.py:96` (`short = len(text) < WHOLE_BELOW`) gegen `chain.py:91-92`
**Was passiert:** `EMPTY_BELOW`/`THIN_BELOW` zählen sichtbare Zeichen, `WHOLE_BELOW`/`WALL_WINDOW` dagegen Roh-Zeichen. Eine Seite mit 500 sichtbaren und 4500 Roh-Zeichen gilt als „lang": Sie wird nur im ersten 2000-Roh-Zeichen-Bereich geprüft (der bei `<head>`-lastigem Markup leer ist) — Paywall-Marker im Artikel werden übersehen. `WHOLE_BELOW` trägt dann seinen Kommentar „shorter texts are checked completely" nicht mehr.
**Fix:** Alle Längenentscheidungen auf `visible` beziehen (`WHOLE_BELOW` und `WALL_WINDOW` an die sichtbare Länge binden).

## 8. Marker-Tests decken `CHALLENGE` und Regex-Überschneidungen nicht ab
**Kategorie:** Testlücke
**Zeile:** `test_chain.py:96-104`
**Was passiert:** `test_each_marker_is_in_one_list_only` prüft nur `WALL + PAYWALL_DEFINITE + PAYWALL`; ein Marker, der in `CHALLENGE` steht und in einer dieser Listen wiederholt wird, fällt durch (dort greift zusätzlich die 1500-Zeichen-Grenze vor der Wall-Prüfung, die Reihenfolge der Listen wäre also nicht mehr eindeutig). `test_no_marker_lies_inside_another_marker_of_its_list` filtert alle Marker mit Regex-Metazeichen heraus (`chain.py`-Listen: `pur[- ]abo`, `spiegel\+`, `nur f(ue|ü)r abonnenten` …) und testet sie nur als *Text*, nie als Muster — eine neue Überschneidung zwischen zwei Regex-Markern wird nicht erkannt. Außerdem fehlt jeder Test dafür, dass `_visible` Script-Inhalte korrekt behandelt (Befund 3).
**Fix:** Alle vier Listen in den Eindeutigkeitstest aufnehmen und Regex-Marker gegeneinander testen (`re.search(a, b)` mit entfernten Metazeichen bzw. per `_WALL_RX[i].search(example_text_j)`).

## 9. `_visible` läuft mehrfach über den vollen Content
**Kategorie:** Performance
**Zeile:** `chain.py:91` sowie `chain.py:152`, `chain.py:197-200`, `chain.py:202`
**Was passiert:** Für jede URL wird `_visible` in `classify` berechnet und danach je nach Pfad noch 2–4 Mal erneut (`_reason`, Längenvergleich in K3, `NOTE_THIN*`). Bei einer 2-MB-Seite sind das 4 zusätzliche Vollpässe mit Regex-Substitution pro URL, obwohl die Länge bereits vorliegt.
**Fix:** `classify` die sichtbare Länge mit zurückgeben lassen (z. B. als Tupel) oder sie einmal in `step()` cachen und an `_reason`/`_result` weiterreichen.

## 10. Zweideutige Namen in `run_chain`
**Kategorie:** Schlechter Stil
**Zeile:** `chain.py:96` gegen `chain.py:185`, dazu `chain.py:188`/`chain.py:208`
**Was passiert:** `short` bedeutet in `classify` „Text unter 4000 Zeichen", in `run_chain` „die bisher kurze TinyFish-Seite"; `page` bezeichnet nacheinander Firecrawl und Keenable. Beides lädt zu Folgefehlern ein (die Bedingung `if short is not None` in `chain.py:201` liest sich, als wäre `short` ein Flag). `check[0]`/`check[1]` in `chain.py:216` ist ebenfalls undokumentiert.
**Fix:** Umbenennen (`is_short_text` vs. `tinyfish_thin`, `fc_page`/`ke_page`) und das Tupel `check` durch zwei benannte Variablen ersetzen.
