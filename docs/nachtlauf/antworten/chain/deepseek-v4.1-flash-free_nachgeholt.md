Nach Prüfung von `chain.py` und den angehängten Tests, sortiert nach Schwere:

**1. Kategorie: Bug / falsche Klassifizierung — `chain.py:83` (mit `chain.py:68`)**
`_visible` entfernt nur `<…>`-Tags, nicht den Inhalt von `<script>`/`<style>`/`<noscript>`. Eingabe: `"Kurzer Text. " + "<script>" + "x"*3000 + "</script>"` → sichtbare Länge ~3013 > `THIN_BELOW` → `"ok"`, obwohl der echte Text 13 Zeichen hat. Ebenso kann ein Bot-Check mit viel Inline-JS über `CHALLENGE_BELOW` (1500) rutschen und die Challenge-Erkennung verlieren. Fix: vor `_TAGS` `re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", "", text)`.

**2. Kategorie: Edge Case — `chain.py:97`**
Die Wall-Prüfung nutzt rohen `text` (inkl. Tags), Challenge/Thin dagegen `_visible`. Eingabe: erste 2000 Raw-Zeichen sind nur `<div class=…>`-Boilerplate, der Consent-Text steht bei Rohposition 2500. Bei `len(text) >= 4000` wird nur `text[:2000]` durchsucht → Wall-Marker werden übersehen, Seite gilt als `thin`/`ok`, obwohl es eine Consent-Wall ist. Fix: Window über `_visible` statt `text` legen.

**3. Kategorie: Logikfehler/Inkonsistenz — `chain.py:208-217`**
`wall_page` wird nur aus TinyFish (Z.184) und Firecrawl (Z.203) gesetzt, nie aus Keenable. Eingabe: `run(doc("Please verify you are human."), Fake(doc(error="Firecrawl: API 500")), Fake(doc(WALL_TEXT)))` → TinyFish=`challenge` (check gesetzt), Keenable=`wall`; da `wall_page is None`, liefert Z.217 die Bot-Check-Seite mit `NOTE_CHECK` und verwirft die Wall. Das widerspricht der in den Tests festgelegten Priorität V5 (wall vor challenge). Fix: bei `kind == "wall"` aus Keenable `wall_page = page` setzen.

**4. Kategorie: Edge Case — `chain.py:99`**
Der 75%-Beschnitt für `full_page` rechnet auf `len(text)` inkl. HTML. Bei script-/style-lastigen Seiten verschiebt sich die Grenze, Footer-Marker (`"SPIEGEL+ Jetzt weiterlesen"`) landen im geprüften Bereich → fälschlich `paywall`. Fix: Anteil auf sichtbaren Text beziehen.

**5. Kategorie: Robustheit — `chain.py:180` und `chain.py:153`**
`tinyfish.get("code") in FINAL_TINYFISH_CODES` wirft `TypeError`, wenn `code` nicht hashbar ist (z. B. Liste/Dict). Da alles im äußeren `except` (Z.219) landet, wird die Kette mit `failure("extract-chain: TypeError")` abgebrochen und Firecrawl/Keenable gar nicht mehr versucht. Ebenso würde `_KIND_TEXT[kind]` (Z.153) bei einem künftig ergänzten Kind `KeyError` werfen. Fix: `isinstance(code, str)`-Prüfung bzw. `_KIND_TEXT.get(kind, kind)`.

**6. Kategorie: Security/Privacy — `chain.py:127` und `chain.py:134`**
Der Log-Pfad vermeidet bewusst die volle URL bzw. Query (weil Tokens enthalten sein können, `_host` Z.142), die Redirect-Notiz und `metadata["finalURL"]` geben aber die finale URL inkl. Query ungekürzt an den Content/das Modell weiter. Fix: Query der finalen URL für Notiz/Metadata entfernen oder nur Schema+Host+Path übernehmen.
