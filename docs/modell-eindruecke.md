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
