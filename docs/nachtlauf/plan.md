# Nachtlauf 2026-10-16: Plan

Branch `review/nachtlauf-2026-10-16`, abgezweigt von `main` nach dem Merge von PR #1 (`c9d5739`).

## Ausgangslage

- Testsuite: `uv run --locked pytest -q` → **176 passed** (0,77 s, Python 3.13 lokal).
- `ruff check` und `ruff format --check`: sauber.
- Gelesen: `extract_chain/*`, `tests/*`, `scripts/live_check.py`, `scripts/replay.py`, `README.md`, `docs/design.md`, `docs/troubleshooting.md`, `docs/validation.md` (überflogen), `docs/evaluation.md` (überflogen), `CHANGELOG.md`.

## Prüfbereiche

Je Bereich gehen Code und zugehörige Tests zusammen als Anhang an die Modelle, zusammen unter ca. 800 Zeilen.

| Bereich | Dateien | Zeilen | Zweck |
|---|---|---|---|
| `fetchers` | `extract_chain/fetchers.py`, `tests/test_fetchers.py` | 196 + 278 | REST-Aufrufe an TinyFish, Firecrawl, Keenable; Fehler in einheitliche Ergebnis-Dicts übersetzen, Keys schwärzen |
| `chain` | `extract_chain/chain.py`, `tests/test_chain.py` | 223 + 503 | Klassifikation der Texte (leer, Bot-Check, Consent-Wall, Paywall, kurz, ok), Ablauf der Kette je URL, Hinweise für das Modell |
| `provider` | `extract_chain/provider.py`, `extract_chain/__init__.py`, `extract_chain/plugin.yaml`, `tests/test_provider.py`, `tests/conftest.py` | 193 + 8 + 20 + 475 + 43 | Schnittstelle zu Hermes: Website-Blocklist, Interrupts, Duplikate, Pausen nach HTTP 402, Registrierung |
| `scripts` | `scripts/live_check.py`, `scripts/replay.py` | 132 + 118 | Entwicklerwerkzeuge: Live-Check über Hermes, Replay auf gespeicherten Rohdaten |

Nicht an die Modelle: `docs/` (Konsistenz Doku ↔ Code prüfe ich selbst), `scripts/second-opinion.sh` (laut Auftrag nach Phase 0 nicht weiter bearbeiten).

## Vorgehen je Bereich

1. Prompt in `docs/nachtlauf/prompts/<bereich>.txt`.
2. `OPINION_COUNT=8 scripts/second-opinion.sh <prompt> <dateien...>`; bei Rate-Limits später nur die gesperrten Modelle über `OPINION_MODELS`.
3. Antworten nach `docs/nachtlauf/antworten/<bereich>/`.
4. Je Modell mit Antwort eine Zeile in `docs/modell-eindruecke.md`.
5. Prüfung jedes Befunds am Code → `docs/nachtlauf/befunde.md`.

## Entscheidungen

- Die Prompts nennen die in `docs/design.md` dokumentierten bewussten Entscheidungen (D16–D18, D10 usw.) als „nicht melden“, damit die Modelle nicht bekannte Ablehnungen wiederholen. So verlangt es auch der Auftrag (nicht neu aufrollen).
- Prompts auf Deutsch, Code und Kommentare sind Englisch.
