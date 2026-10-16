# Eindrücke der Review-Modelle

Eine Zeile je Modell und Review. Spalten: Modell-ID (exakt, ohne `opencode/`), Datum, PR/Branch, Dauer, Punkte gesamt / übernommen / Fehlalarme, Kurzurteil.

| Modell | Datum | PR | Dauer | Punkte ges./übern./Fehlalarm | Kurzurteil |
|---|---|---|---|---|---|
| muse-spark-1.3-contributor-free | 2026-10-16 | chore/second-opinion (Testlauf) | 25s | 5/0/1 | Knapp und präzise. Treffer: Rotation bevorzugt ll-alpha nicht, Rate-Limit-String fragil, npm ohne Pin. Fehlalarm: `big-pickle` ohne `-free` ist korrekt. Zeilennummern falsch. |
| space-bunny-free | 2026-10-16 | chore/second-opinion (Testlauf) | 45s | 6/0/0 | Gründlichste Antwort mit korrekten Zeilen. Starke Treffer: alte `.opinion/*.md` bleiben liegen, fehlender Anhang wird als Modellfehler gemeldet, OPINION_MODELS verkleinert POOL. Waisen-Prozess und Worktree-Punkt etwas übertrieben. |
| cat-jam-free | 2026-10-16 | chore/second-opinion (Testlauf) | 15s | 5/0/3 | Schnell, aber dünn. Nur Basename-Kollision der Anhänge stichhaltig. Timeout/Kindprozess, Word-Splitting und exclude-Duplikat sind Fehlalarme. Zeilennummern erfunden. |
