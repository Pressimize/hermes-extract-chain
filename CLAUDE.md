## Zweite Meinung durch andere Modelle

Vor jedem Push einer Änderung am Code (nicht bei reinen Doku-Tippfehlern) holt Claude Code drei unabhängige Reviews über `scripts/second-opinion.sh` ein:

1. Diff erzeugen: `git diff origin/main...HEAD > /tmp/diff.txt` (bei Plänen stattdessen die Plan-Datei).
2. Prompt-Datei schreiben: Ziel der Änderung in zwei Sätzen, Bitte um höchstens 10 Punkte (Bugs, Risiken, fehlende Tests) mit Datei und Zeile, keine Stilfragen.
3. `scripts/second-opinion.sh /tmp/prompt.txt /tmp/diff.txt` — Antworten liegen in `.opinion/<modell>.md`.
4. Jeden Punkt selbst am Code prüfen, nicht ungeprüft übernehmen. Übernommene Punkte umsetzen, abgelehnte mit kurzem Grund im Design-Dokument festhalten, wenn es den geänderten Teil beschreibt, sonst im PR-Text.
5. Im PR-Text kurz zusammenfassen: welche Modelle, was übernommen, was abgelehnt.
6. Je Modell mit Antwort eine Zeile in `docs/modell-eindruecke.md` anhängen. Rate-Limits, Timeouts und Fehler trägt das Skript selbst in `docs/modell-fehlversuche.md` ein. Beide Dateien mitcommitten. Das Skript fragt die zwei besten verfügbaren Modelle der Rangfolge und zusätzlich ein Rotationsmodell, nämlich das mit den wenigsten Zeilen in beiden Dateien zusammen. So sammeln sich nach und nach Eindrücke von allen Free-Modellen.

Rangfolge (Andres Einschätzung 2026-10-16): Muse Spark 1.3 > Space Bunny > DeepSeek v4.1 Flash, Cat Jam, GLM 5.3 Flash, MiMo 2.6 Flash > Longcat 2.5, Big Pickle. LL Alpha ist neu und unbewertet. Jev und Nemotron werden nicht genutzt. Weicht der Eindruck nach mehreren Läufen deutlich davon ab, im PR-Text darauf hinweisen; die Rangfolge im Skript ändert nur Andre.

Hinweise: Die Free-Modelle brauchen keinen Key, laufen aber nur über den `opencode`-Client. Ein Rate-Limit sieht ohne Logs wie ein Hänger aus; das Skript erkennt es und nimmt das nächste Modell. Antworten können vereinzelte fremdsprachige Zeichen enthalten. Keine Secrets in Prompts oder Anhänge.
