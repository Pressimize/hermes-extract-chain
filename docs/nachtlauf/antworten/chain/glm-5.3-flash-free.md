## Prüfung: `extract_chain/chain.py`

**1. Robustheit/Bug — chain.py:124-125**
`pdf_pages` wird blind als 2-Element-Container entpackt: `shown=pages[0], total=pages[1]`. Ein truthy-Wert mit einem Element (z.B. `pdf_pages=[120]` oder `pdf_pages=(120,)`) wirft `IndexError` in `_result`. Da `_result` innerhalb des großen `try` aufgerufen wird, fängt run_chain (chain.py:219-221) das ab — und ein völlig brauchbares Result (kein Fehler, guter Text) wird zu `failure(url, "extract-chain: IndexError")`, die ganze URL verliert damit ihren Content nur wegen eines kosmetischen Nebenzettels. Fix: vor dem Format prüfen `if isinstance(pages, (list, tuple)) and len(pages) >= 2`, oder die Notiz in ein eigenes minimales try setzen, das das Ergebnis nicht berühren kann.

**2. Security/Robustheit — chain.py:150-153 (betroffen: 129-131, 213, 218; zusätzlich 133-134)**
Anbieter-Fehlermeldungen (`doc["error"]`, in Tests z.B. „Keenable: Gateway timeout") fließen ungesäubert über `_reason` → `reasons` → `NOTE_* .format(reasons="; ".join(reasons))` in `content` und das `error`-Feld. Enthält eine Fehlermeldung einen Zeilenumbruch oder selbst `Warning unter this`/`[extract-chain] …`, bricht der Ein-Notiz-pro-Zeile-Vertrag (chain.py:130-131, Trennung per `\n`) und eine erfundene Notizzeile wird dem Sprachmodell untergeschoben — an derselben Schnittstelle, die chain.py:127 für `final_url` sorgfältig selbst vorbereitet. Fix: wie in chain.py:127Whitespace kollabieren (`" ".join(err.split())`) und `finalURL` in `metadata` (chain.py:134) ebenfalls kappen.

**3. Edge Case — chain.py:96-100 (Einheiten-Inkonsistenz zu chain.py:14-18, 82-83)**
E2/E7/E8‑Grenzwerte gelten laut Kommentar über sichtbare Zeichen, aber `WHOLE_BELOW` und der WALL-/PAYWALL‑Scan laufen auf dem rohen `text` inklusive Markup. Konkret: Dokument mit < 4000 rohen Zeichen, dessen Markup zwei WALL‑Formulierungen enthält (z.B. `id="cookie-einstellungen"` plus `aria-label="Alle akzeptieren"`), aber echten Artikeltext → classifiziert als `wall`, disturbing Umleitung zur Keenable, obwohl die Seite ok ist. Fix: WALL‑ und PAYWALL‑Scan ebenfalls auf `_visible(doc)` beschränken oder die Absicht (roh) an der Stelle als Kommentar/docstring festhalten.

**4. Edge Case — chain.py:73, 117-118**
`_LOCALE` gleicht überbeliebige 2-/4-Buchstaben-Slugs: Redirect von `/jobs` nach `/it` erzeugt die Redirect-Notiz, obwohl „it" ein Artikel-Slug sein kann (z.B. IT-Ressort), ebenso „or", „hi", „de". Test deckt nur `/deutsch/` (chain.py:464), nicht den Slug-Fall. Fix: kleine feste Liste echter Locale-Codes als Konstante (passt zum Entwicklungsprinzip), oder zusätzlich verlangen, dass der angeforderte Pfad selbst nicht locale-ähnlich ist.

**5. Stil/Best Practice — chain.py:192, 212**
`*notes, *([NOTE_PAYWALL] if kind == "paywall" else [])` ist zweimal identisch, schwer lesbar und kann beim Weglassen der Klammern still zu `*NOTE_PAYWALL` zeichenweise splitten — ein kleines Bug-Fenster. Fix: kleine lokale Helferfunktion `def _with_paywall(kind_, *ns): return (*ns, *( [NOTE_PAYWALL] if kind_=="paywall" else [] ))` oder in `_result` optionalen Parameter `paywall_note=…` mitführen.

Sonst keine belastbaren Befunde: Regexe vorkompiliert, `except Exception` đặt nur an den vorgesehenen S6-Stellen, CancelledError bleibt nicht verschluckt (BaseException, gut für Hermes' Interrupt), Logzeile enthält nie die volle URL (belegt durch tests/test_chain.py:273-283), `$KIND_TEXT`-fehlende Einträge (`paywall`, `ok`) sind bei heutigem Kontrollfluss unerreichbar.
