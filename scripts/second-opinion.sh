#!/usr/bin/env bash
# Zweite Meinung von kostenlosen OpenCode-Modellen einholen (ohne API-Key).
# Aufruf: scripts/second-opinion.sh <prompt-datei> [anhang ...]
# Ergebnis: .opinion/<modell>.md je Modell, Logs in .opinion/<modell>.log
# Modelle per Umgebungsvariable OPINION_MODELS (Leerzeichen-getrennt) ueberschreibbar.
set -uo pipefail

PROMPT_FILE="${1:?Prompt-Datei fehlt}"; shift
# Rangfolge nach Andres Einschaetzung (2026-10-16), beste zuerst.
RANKED="${OPINION_MODELS:-muse-spark-1.3-contributor-free space-bunny-free deepseek-v4.1-flash-free cat-jam-free glm-5.3-flash-free mimo-v2.6-flash-free longcat-2.5-preview-free big-pickle}"
# Zusaetzlich je Lauf ein Rotationsmodell: das mit den wenigsten Eintraegen in EINDRUECKE,
# bei Gleichstand zuerst unbewertete, dann die hinteren der Rangfolge (die vorderen kommen ohnehin dran).
POOL="${OPINION_POOL:-ll-alpha-free big-pickle longcat-2.5-preview-free mimo-v2.6-flash-free glm-5.3-flash-free cat-jam-free deepseek-v4.1-flash-free space-bunny-free muse-spark-1.3-contributor-free}"
WANT="${OPINION_COUNT:-2}"        # so viele erfolgreiche Antworten aus RANKED
TIMEOUT="${OPINION_TIMEOUT:-400}"

command -v opencode >/dev/null || npm i -g opencode-ai >/dev/null 2>&1 || { echo "opencode-Installation fehlgeschlagen" >&2; exit 1; }

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
WORK="$ROOT/.opinion"

# Erst alles pruefen und einlesen, dann den Arbeitsordner leeren (Anhaenge koennen in .opinion/ liegen).
[ -r "$PROMPT_FILE" ] && [ -s "$PROMPT_FILE" ] || { echo "Prompt-Datei fehlt oder ist leer: $PROMPT_FILE" >&2; exit 1; }
PROMPT="$(cat "$PROMPT_FILE")"
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
NAMES=()
for f in "$@"; do
  [ -f "$f" ] || { echo "Anhang fehlt: $f" >&2; exit 1; }
  b="$(basename "$f")"
  [[ " ${NAMES[*]-} " == *" $b "* ]] && { echo "Doppelter Anhang-Dateiname: $b" >&2; exit 1; }
  cp "$f" "$STAGE/$b" || { echo "Anhang nicht kopierbar: $f" >&2; exit 1; }
  NAMES+=("$b")
done

rm -rf "$WORK"   # Reste frueherer Laeufe nicht mit neuen verwechseln
mkdir -p "$WORK"
grep -qx '.opinion/' "$ROOT/.git/info/exclude" 2>/dev/null || echo '.opinion/' >> "$ROOT/.git/info/exclude"
# Anhaenge muessen im Arbeitsordner liegen, sonst lehnt opencode den Lesezugriff ab.
ATTACH=()
for b in ${NAMES[@]+"${NAMES[@]}"}; do
  cp "$STAGE/$b" "$WORK/$b" || { echo "Anhang nicht kopierbar: $b" >&2; exit 1; }
  ATTACH+=(-f "$b")
done

EINDRUECKE="$ROOT/docs/modell-eindruecke.md"
FEHLVERSUCHE="$ROOT/docs/modell-fehlversuche.md"   # schreibt das Skript selbst, mitcommitten
# Rotation zaehlt Antworten und Fehlversuche, damit ein Modell ohne Antwort nicht jeden Lauf zuerst drankommt.
count_rows() { local a b; a=$(grep -c "^| $1 |" "$EINDRUECKE" 2>/dev/null); b=$(grep -c "^| $1 |" "$FEHLVERSUCHE" 2>/dev/null); echo $(( ${a:-0} + ${b:-0} )); }
fail() {  # fail <modell> <grund> <dauer>
  [ -f "$FEHLVERSUCHE" ] || printf '# Fehlversuche der Review-Modelle

Vom Skript geschrieben, zaehlt fuer die Rotation mit.

| Modell | Datum | Grund | Dauer |
|---|---|---|---|
' > "$FEHLVERSUCHE"
  echo "| $1 | $(date +%F) | $2 | ${3}s |" >> "$FEHLVERSUCHE"
}

ask() {  # ask <modell> -> 0 bei Antwort
  local m="$1" out log start pid rc dur g
  TRIED+=("$m")
  out="$WORK/$m.md"; log="$WORK/$m.log"
  start=$(date +%s)
  # Prompt vor -f, sonst liest opencode ihn als Dateinamen.
  ( cd "$WORK" && exec timeout "$TIMEOUT" opencode run -m "opencode/$m" "$PROMPT" ${ATTACH[@]+"${ATTACH[@]}"} \
      --print-logs --log-level INFO >"$out" 2>"$log" ) &
  pid=$!
  # Bei Rate-Limit haengt der Client still; Log beobachten und frueh abbrechen.
  while kill -0 "$pid" 2>/dev/null; do
    grep -q "Rate limit exceeded" "$log" 2>/dev/null && { kill "$pid" 2>/dev/null; break; }
    sleep 5
  done
  wait "$pid"; rc=$?; dur=$(( $(date +%s) - start ))
  if grep -q "Rate limit exceeded" "$log"; then
    echo "[$m] Rate-Limit nach ${dur}s"; rm -f "$out"; fail "$m" "Rate-Limit" "$dur"; return 1
  fi
  if [ $rc -ne 0 ] || [ ! -s "$out" ]; then
    if [ $rc -eq 124 ]; then g="Timeout"; else g="Fehler rc=$rc"; fi
    echo "[$m] $g (${dur}s), siehe $log"; rm -f "$out"; fail "$m" "$g" "$dur"; return 1
  fi
  echo "[$m] ok (${dur}s) -> $out"; USED+=("$m"); return 0
}

USED=(); TRIED=()
ok=0
for m in $RANKED; do
  [ "$ok" -ge "$WANT" ] && break
  ask "$m" && ok=$((ok+1))
done

# Rotation: am wenigsten erprobtes Modell, das in diesem Lauf noch nicht gefragt wurde.
rot=""
for m in $(for p in $POOL; do echo "$(count_rows "$p") $p"; done | sort -n -s -k1,1 | cut -d' ' -f2); do
  [[ " ${TRIED[*]-} " == *" $m "* ]] && continue
  ask "$m" && { echo "[Rotation] $m"; rot=1; break; }
done
[ -n "$rot" ] || echo "[Rotation] kein weiteres Modell hat geantwortet"

[ "${#USED[@]}" -gt 0 ] || { echo "Keine Antwort erhalten." >&2; exit 2; }
echo "Bitte je Modell mit Antwort eine Zeile in docs/modell-eindruecke.md eintragen (Rate-Limit/Fehler: keine Zeile, die stehen schon in docs/modell-fehlversuche.md)."
