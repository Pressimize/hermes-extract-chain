# Eindrücke der Review-Modelle

Eine Zeile je Modell und Review. Spalten: Modell-ID (exakt, ohne `opencode/`), Datum, PR/Branch, Dauer, Punkte gesamt / übernommen / Fehlalarme, Kurzurteil.

| Modell | Datum | PR | Dauer | Punkte ges./übern./Fehlalarm | Kurzurteil |
|---|---|---|---|---|---|
| muse-spark-1.3-contributor-free | 2026-10-16 | chore/second-opinion (Testlauf) | 25s | 5/0/1 | Knapp und präzise. Treffer: Rotation bevorzugt ll-alpha nicht, Rate-Limit-String fragil, npm ohne Pin. Fehlalarm: `big-pickle` ohne `-free` ist korrekt. Zeilennummern falsch. |
| space-bunny-free | 2026-10-16 | chore/second-opinion (Testlauf) | 45s | 6/0/0 | Gründlichste Antwort mit korrekten Zeilen. Starke Treffer: alte `.opinion/*.md` bleiben liegen, fehlender Anhang wird als Modellfehler gemeldet, OPINION_MODELS verkleinert POOL. Waisen-Prozess und Worktree-Punkt etwas übertrieben. |
| cat-jam-free | 2026-10-16 | chore/second-opinion (Testlauf) | 15s | 5/0/3 | Schnell, aber dünn. Nur Basename-Kollision der Anhänge stichhaltig. Timeout/Kindprozess, Word-Splitting und exclude-Duplikat sind Fehlalarme. Zeilennummern erfunden. |
| muse-spark-1.3-contributor-free | 2026-10-16 | #1 (Testlauf 2) | 40s | 5/0/2 | Korrekte Zeilen, Hauptbefund getroffen: `rm -rf` vor Prüfung von Prompt und Anhängen, Anhänge aus `.opinion/` werden gelöscht. Fehlalarme: POOL-Drift (gewollt), Substring-Match in TRIED (durch Leerzeichen exakt). |
| space-bunny-free | 2026-10-16 | #1 (Testlauf 2) | 60s | 5/0/2 | Wieder am gründlichsten. Gleicher Hauptbefund wie Muse Spark, dazu parallele Läufe und fragiles `count_rows`. Fehlalarme: `rm -rf`-Pfadabsicherung (WORK endet immer auf `/.opinion`), POOL-Drift (gewollt). |
| longcat-2.5-preview-free | 2026-10-16 | #1 (Testlauf 2) | 55s | 4/0/2 | Ordentlich formuliert, aber flach. Trifft destruktives `rm -rf` und parallele Läufe, übersieht gelöschte Anhänge in `.opinion/`. Fehlalarme: `count_rows` kann nicht leer ausgeben, `ask` ohne Antwortdatei ist durch `-s`-Prüfung ausgeschlossen. Keine Zeilennummern. |
| glm-5.3-flash-free | 2026-10-16 | #1 (Testlauf 3) | 60s | 5/0/1 | Solide mit korrekten Zeilen. Treffer: ungeprüftes `mktemp`, fragiles `count_rows`, parallele Läufe ohne Lock, 5-s-Polling. Fehlalarm: Rate-Limit-Kill würde einen erfolgreichen Retry verwerfen bzw. als rc=143 buchen (das Log-grep fängt das ab). |
| mimo-v2.6-flash-free | 2026-10-16 | #1 (Testlauf 3) | 101s | 5/0/1 | Bester Lauf 3, korrekte Zeilen. Eigener guter Fund: Anhang `<modell>.md` kollidiert mit Ausgabedatei. Dazu `mktemp`, vergessene Eindruck-Zeilen verfälschen die Rotation, fehlende Tests. Fehlalarm: Fehlversuche mitzählen ist gewollt. |
| longcat-2.5-preview-free | 2026-10-16 | #1 (Testlauf 3) | 175s | 4/0/2 | Langsam und flach. Regex-Punkte in `count_rows` (vorgeschlagener Fix `grep -cF "^| ..."` wäre falsch), leere Fehlversuchsdatei ohne Kopf. Fehlalarme: Fehlversuche mitzählen und getrackte Datei sind gewollt. Keine Zeilennummern. |
| space-bunny-free | 2026-10-16 | review/nachtlauf-2026-10-16 (fetchers) | 110s | 9/1/8 | Gründlich, korrekte Zeilen, liest das ganze Repo und schreibt eigene Probe-Skripte. Treffer: N02 (Firecrawl `data` kein Objekt). Rest: hypothetische API-Formen (`success`/`statusCode` als String), künstlich kurze Keys, Stil. |
| space-bunny-free | 2026-10-17 | review/nachtlauf-2026-10-16 (chain) | 95s | 10/0/10 | Übersieht N01, obwohl es `_visible` mehrfach kritisiert. Will Marker im sichtbaren statt im Roh-Text suchen, was E3 ausdrücklich anders festlegt. Gut begründet, aber oft gegen dokumentierte Entscheidungen. |
| space-bunny-free | 2026-10-17 | review/nachtlauf-2026-10-16 (provider) | ~140s | 8/0/8 | Hat `docs/design.md` gelesen und rollt trotzdem K7 (00:05-Grenze) neu auf. Hauptpunkt (Keyless-Rescue holt blockierte URLs) am Hermes-Quelltext v0.21.6 widerlegt. |
| space-bunny-free | 2026-10-17 | review/nachtlauf-2026-10-16 (scripts) | 55s | 10/2/8 | Schnell (ohne Werkzeuge). Treffer N04 und N05 auf Platz 1 und 3; Rest Entwicklerskript-Kosmetik. |
| deepseek-v4.1-flash-free | 2026-10-17 | review/nachtlauf-2026-10-16 (chain) | 251s | 8/1/7 | Bester Einzelfund der Nacht: N01 (`<[^>]*>`) mit beiden Folgen und eigener Messung, als einziges unabhängiges Modell. Übrige Punkte ehrlich als gering markiert. |
| deepseek-v4.1-flash-free | 2026-10-17 | review/nachtlauf-2026-10-16 (provider) | 356s | 5/0/5 | Liest das Design und lässt dokumentierte Punkte bewusst weg. Gemeldet nur Latentes (Iterator statt Liste, `KeyError` bei hypothetischen Docs, `60 min`). |
| deepseek-v4.1-flash-free | 2026-10-17 | review/nachtlauf-2026-10-16 (scripts) | 50s | 9/2/7 | N04 und N05 auf Platz 1 und 2, präzise. Rest hypothetisch. |
| deepseek-v4.1-flash-free | 2026-10-17 | review/nachtlauf-2026-10-16 (fetchers) | 115s | 5/1/4 | Knapp, trifft N02. Einzel-URL-Fallback kritisiert, obwohl A1 ihn so vorsieht. |
| glm-5.3-flash-free | 2026-10-17 | review/nachtlauf-2026-10-16 (scripts) | 406s | 10/2/8 | Treffer N04 und N05. Langsam; Antwort endet mit einer Fremdzeile („Load not found …“). |
| glm-5.3-flash-free | 2026-10-17 | review/nachtlauf-2026-10-16 (fetchers) | 295s | 9/0/9 | Nur dokumentierte (A1, L1) oder hypothetische Punkte; N02 übersehen. |
| glm-5.3-flash-free | 2026-10-17 | review/nachtlauf-2026-10-16 (chain) | 430s | 5/0/5 | N01 übersehen; Punkte wiederholen bereits abgelehnte Themen. |
| glm-5.3-flash-free | 2026-10-17 | review/nachtlauf-2026-10-16 (provider, Wiederholung) | 235s | 5/0/5 | Nur Duplikate (K7-Grenze, `is_available`, Pausengrund). Erster Versuch: 900 s Timeout nach 49.000 Token Nachdenken ohne Antwort. |
| mimo-v2.6-flash-free | 2026-10-17 | review/nachtlauf-2026-10-16 (scripts) | 185s | 10/2/8 | N04 und N05 auf Platz 1 und 2. Bei den anderen Bereichen meist Timeout (Strom startet, liefert 0 Token). |
| mimo-v2.6-flash-free | 2026-10-17 | review/nachtlauf-2026-10-16 (fetchers, Wiederholung) | 386s | 8/1/7 | Trifft N02. Kreative, aber für echte Keys irrelevante Idee (JSON-escaptes `/` im Key). |
| longcat-2.5-preview-free | 2026-10-17 | review/nachtlauf-2026-10-16 (provider) | 676s | 0/0/0 | Unbrauchbar: nur Zwischentext („Ich lese die Dateien …“), keine Befunde. |
| longcat-2.5-preview-free | 2026-10-17 | review/nachtlauf-2026-10-16 (scripts) | 115s | 10/1/9 | Trifft N05, übersieht N04. Eine Fehllesung (`getMessage()` verfälsche das Präfix). |
| longcat-2.5-preview-free | 2026-10-17 | review/nachtlauf-2026-10-16 (fetchers) | 721s | 3/0/3 | Sehr langsam, wenig Inhalt (String-`statusCode`, Host-Großschreibung, MB-Fehlerseiten). |
| longcat-2.5-preview-free | 2026-10-17 | review/nachtlauf-2026-10-16 (provider, Wiederholung) | 426s | 3/0/3 | Nur Duplikate. |
| big-pickle | 2026-10-17 | review/nachtlauf-2026-10-16 (chain) | 311s | 9/–/– | Zählt nicht: hat per `cat .opinion/…md` die Antworten von DeepSeek und Space Bunny gelesen und übernommen (nachgewiesen in der opencode-Datenbank) und den bereits umgesetzten Fix im Arbeitsbaum gesehen. |
| big-pickle | 2026-10-17 | review/nachtlauf-2026-10-16 (provider) | 145s | 10/0/10 | Viele Punkte, keiner trägt; eine Fehllesung (Pause bei `left == 0`). |
| big-pickle | 2026-10-17 | review/nachtlauf-2026-10-16 (scripts) | 165s | 10/0/10 | Übersieht N04 und N05, viel Stil und Spekulation. |
| big-pickle | 2026-10-17 | review/nachtlauf-2026-10-16 (fetchers) | 265s | 5/0/5 | Nur dokumentiertes Verhalten (A1) kritisiert. |
| beam-free | 2026-10-17 | review/nachtlauf-2026-10-16 (provider) | 40s | 7/0/7 | Neu, sehr schnell, knappe Stichpunkte mit korrekten Zeilen, aber nur Latentes. |
| beam-free | 2026-10-17 | review/nachtlauf-2026-10-16 (scripts) | 20s | 9/0/9 | Übersieht N04 und N05. |
| beam-free | 2026-10-17 | review/nachtlauf-2026-10-16 (fetchers) | 35s | 7/0/7 | Eine sachlich falsche Aussage (`UnicodeDecodeError` sei kein `ValueError`). |
| beam-free | 2026-10-17 | review/nachtlauf-2026-10-16 (chain) | 66s | 5/0/5 | N01 übersehen; nur hypothetische Typfehler. |
