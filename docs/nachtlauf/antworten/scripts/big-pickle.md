### 1. **Sicherheitsrisiko (Umgebungsmanipulation) – hohes Risiko**

**Kategorie:** Security  
**Datei und Zeilennummer:** `live_check.py:35–36`  
**Was genau passiert:**
```python
for k in [k for k in os.environ if k.endswith("_API_KEY")]:
    os.environ.pop(k)
```
Beim Laden eines Profils werden **alle** Umgebungsvariablen entfernt, deren Name auf `_API_KEY` endet. Das geschieht global im Prozess (inkl. möglicher Elternprozesse/Threads im gleichen Python-Prozess). Wenn `live_check.py` z. B. in einem Umfeld gestartet wird, in dem andere Schlüssel (z. B. `CI_API_KEY`, `MONITOR_API_KEY`) benötigt werden oder nachfolgender Code darauf zugreift, verschwinden diese ohne Rückmeldung.  
**Vorschlag zur Behebung:** Nur solche Keys entfernen, die tatsächlich vom Hermes-Profil überschrieben werden sollen (z. B. bekannte Provider-Namen) oder gezielt die Keys des vorherigen Profils. Alternativ nur innerhalb eines sauberen Subprozesses laufen lassen oder eine Kopie von `os.environ` für den Import verwenden.

---

### 2. **Absturz bei nicht erwarteter Log-Zeile (IndexError) – hohes Risiko**

**Kategorie:** Bug / Edge Case  
**Datei und Zeilennummer:** `live_check.py:104`  
**Was genau passiert:**
```python
by_host = {line.split(" ", 2)[1].rstrip(":"): line for _, line in collect.lines}
```
`collect.lines` enthält nur Einträge, deren `record.getMessage()` mit `"extract-chain "` beginnt (Zeile 53–54). Die Annahme ist, dass jede dieser Zeilen das Format `"extract-chain <host>: ..."` hat (mindestens zwei Leerzeichen nach Prefix). Trägt das Plugin z. B. eine Zeile wie `"extract-chain: fehlender Host"` oder `"extract-chain "` ohne Host ein, wirft `line.split(" ", 2)[1]` einen `IndexError` und bricht die Auswertung der gesamten Gruppe ab.  
**Vorschlag zur Behebung:** Nur Zeilen verarbeiten, die dem erwarteten Muster entsprechen (z. B. `re.match(r"^extract-chain ([^:]+):", line)`) oder defensiv prüfen, ob `len(parts) >= 2` ist.

---

### 3. **Falsche Problem-Meldung bei leerem Keenable-Ergebnis – mittleres Risiko**

**Kategorie:** Edge Case  
**Datei und Zeilennummer:** `live_check.py:107–109`  
**Was genau passiert:**
```python
if ("keenable=ok" in line or "keenable=paywall" in line) and not content.startswith(KEENABLE_NOTE):
    problems.append(f"{case['id']}: Keenable result without note")
```
`KEENABLE_NOTE = "[extract-chain] Copy from Keenable's index"` (Zeile 28). Wenn Keenable `ok`/`paywall` meldet, aber `content` leer ist (`""`), dann ist `startswith` `False` – es wird fälschlicherweise ein Problem gemeldet, obwohl der Inhalt tatsächlich leer (und kein Text mit Note existiert). Die Prüfung sollte zwischen „Inhalt vorhanden, aber ohne Note“ und „Inhalt leer“ unterscheiden.  
**Vorschlag zur Behebung:** Bedingung ergänzen, z. B. `content and not content.startswith(...)` oder explizit prüfen, ob ein nicht-leerer Text erwartet wird.

---

### 4. **Fragile Extraktion des ersten Log-Blocks (String-Slicing) – mittleres Risiko**

**Kategorie:** Robustheit  
**Datei und Zeilennummer:** `live_check.py:111–112`  
**Was genau passiert:**
```python
first = content.split("\n", 1)[0] if content.startswith("[extract-chain]") else ""
...
f"len={len(content):>6}  {first[16:70]}"
```
Es wird vorausgesetzt, dass der Prefix exakt `" [extract-chain]"` + Leerzeichen ist und mindestens 16 Zeichen lang (Zeile 28 zeigt `[extract-chain] Copy...` = 16 Zeichen vor `Copy`?). Änderungen am Plugin-Format (z. B. anderes Präfix, zweisprachig) oder ein abweichender Prefix führen zu einem leeren/fehlerhaften Slice. Zudem wird `error` aus `res.get('error')` ungeprüft angehängt.  
**Vorschlag zur Behebung:** Prefix nicht hart slicen (z. B. `first.removeprefix("[extract-chain] ").strip()[:54]`) oder Regex verwenden.

---

### 5. **Quadratische Laufzeit bei Rate-Berechnung – Performance**

**Kategorie:** Performance  
**Datei und Zeilennummer:** `live_check.py:122–127`  
**Was genau passiert:**
```python
for provider, ts in stamps.items():
    ts.sort()
    peak = max(sum(1 for t in ts if s <= t < s + 60) for s in ts)
```
Für jeden Zeitstempel `s` in `ts` wird über alle `ts` iteriert (`sum`), um Fenster von 60 s zu zählen. Bei vielen URLs (z. B. hunderte Aufrufe eines Providers) ist das O(n²) und unnötig langsam.  
**Vorschlag zur Behebung:** Sliding-Window über sortierte Liste (z. B. zwei Pointer) statt verschachtelter Schleifen: O(n log n) insgesamt (Sortieren) bzw. O(n).

---

### 6. **Unbeabsichtigte Modifikation des globalen `sys.path` – Best Practice**

**Kategorie:** Abweichung von Best Practices  
**Datei und Zeilennummer:** `live_check.py:37`, `replay.py:24`  
**Was genau passiert:**
- `live_check.py:37`: `sys.path.insert(0, os.path.join(ROOT, "hermes-agent"))`
- `replay.py:24`: `sys.path.insert(0, str(Path(__file__).resolve().parents[1]))` (Repo-Root)

Beides verändert `sys.path` global für den gesamten Prozess. Bei parallelen Tests oder nachfolgendem Code kann das zu Modul-Sichtbarkeitskonflikten (Shadowing lokaler Module) führen. Insbesondere das Einfügen des Hermes-Roots ist eine Seiteneffekt-behaftete Initialisierung.  
**Vorschlag zur Behebung:** `sys.path` nur temporär ändern (z. B. `with contextlib.ExitStack()` + `sys.path.insert`) oder `importlib` mit explizitem Pfad nutzen. Für Hermes-Import zumindest dokumentieren bzw. nach Import wieder bereinigen.

---

### 7. **IndexError bei leerer Closing-Liste – Bug**

**Kategorie:** Bug / Edge Case  
**Datei und Zeilennummer:** `replay.py:71–75`, `replay.py:109–111`  
**Was genau passiert:**
In `complete()` wird `norm(sentences[0])` und bei `old`-Fall `sentences[1]` zugegriffen, ohne zu prüfen, ob `sentences` leer ist. Wenn in `CLOSING` für eine ID eine leere Liste `[]` steht, löst `sentences[0]` einen `IndexError` aus.  
**Vorschlag zur Behebung:** Prüfen, ob `sentences` nicht leer ist, sonst `"no"` zurückgeben (oder Logging/Fehler mit ID).

---

### 8. **Fragile Prefix-Erkennung in `source()` – Robustheit**

**Kategorie:** Edge Case  
**Datei und Zeilennummer:** `replay.py:78–82`  
**Was genau passiert:**
```python
first = out["content"].split("\n", 1)[0]
for name, note in (("firecrawl", NOTE_FIRECRAWL), ("keenable", NOTE_KEENABLE), ("none", NOTE_WALL)):
    if first.startswith(note.split("(", 1)[0]):
        return name
```
Die Erkennung erfolgt über `note.split("(", 1)[0]` (z. B. wird `"Wall"` statt des vollen Texts verglichen). Das setzt voraus, dass der Plugin-Prefix genau mit diesem Token beginnt. Ändert sich die Notiz (z. B. Klammer entfällt, anderes Format), schlägt die Zuordnung fehl und `source()` fällt auf `"tinyfish"` zurück, obwohl der Text nicht von TinyFish stammt – was die Auswertung (`prototype/plugin`) verfälschen kann.  
**Vorschlag zur Behebung:** Explizit das tatsächliche Prefix prüfen (z. B. `first.startswith(NOTE_FIRECRAWL.splitlines()[0])` oder das exakte Prefix-Format verwenden).

---

### 9. **Speicherverbrauch durch Duplikation von Rohdaten – Performance**

**Kategorie:** Performance  
**Datei und Zeilennummer:** `live_check.py:94–98`  
**Was genau passiert:**
Pro Gruppe wird `row = {..., "raw": raw}` geschrieben (Zeile 95). `raw` ist der komplette JSON-String, den `web_extract_tool` zurückgibt (Zeile 88). Dieser String enthält bereits alle Inhalte der Gruppe. In `results.jsonl` wird dieser String **pro Zeile (pro Gruppe)** erneut als Feld gespeichert. Bei mehreren Gruppen summiert sich der Speicher- und Plattenverbrauch (Duplikate).  
**Vorschlag zur Behebung:** `raw` nur bei Bedarf speichern (z. B. Flag `--save-raw`) oder nach erfolgreichem Parsen nicht duplizieren. Alternativ nur geparste Struktur speichern.

---

### 10. **Unklare Fehlerbehandlung bei JSON-Parse – Stil/Robustheit**

**Kategorie:** Schlechter Stil / Edge Case  
**Datei und Zeilennummer:** `live_check.py:90–93`  
**Was genau passiert:**
```python
try:
    results = json.loads(raw).get("results") or []
except (ValueError, AttributeError):
    results = []
```
Falls `raw` kein valides JSON ist, wird `results = []` gesetzt, aber der Fehler wird nicht protokolliert. Gleichzeitig wird `raw` trotzdem in die JSONL geschrieben (Zeile 96). Die nachfolgende Prüfung (Zeile 102–104) vergleicht URLs mit `[]` und erzeugt generische Probleme – die Ursache (ungültige Tool-Antwort) bleibt im Log aber unklar.  
**Vorschlag zur Behebung:** Den Parse-Fehler in `problems` (oder in `row["log"]`-ähnlich) erfassen, z. B. `problems.append(f"{ids}: invalid JSON from web_extract")` inklusive kurzer Fehlermeldung.
