## Befunde (geordnet nach Schwere)

**1. Edge Case / Funktionsbug — Diskontinuität der TinyFish-Pause exakt um 00:05 UTC**
- Datei: `provider.py:57` (`_pause_seconds`), ausgewertet über `:182` (`left <= DAY`) und `:191`
- `DAY - (now - TINYFISH_RESET_GRACE) % DAY` liefert bei `now ≡ 300 (mod 86400)`, also exakt 00:05:00,000000 UTC, `86400 - 0 = 86400` s. Eine Sekunde zuvor (00:04:59,999) sind es ~1 s. Konkrete Auslösung: TinyFish antwortet mit HTTP 402 im exakten Boundary-Zeitpunkt (Uhr ist injizierbar, Tests stellen sie direkt ein). Der Guard `_paused_doc` akzeptiert `left == DAY` (`<=`), die Pause wird also gesetzt und gilt 24 h — obwohl die Tagesgrenze gerade erneuert wurde und die Grace-Periode genau solche 402s abfedern soll. Fix: `(TINYFISH_RESET_GRACE - now) % DAY` rechnen; der bestehende Guard `0 < left` behandelt 0 dann als „keine Pause" und TinyFish wird sofort neu gefragt.

**2. Robustheit — Interrupt-Fähigkeit geht still verloren**
- Datei: `provider.py:40-45`
- Ist `tools.interrupt` nach einem Hermes-Update nicht mehr importierbar, schreibt der Fallback `is_interrupted` dauerhaft `False` — ohne jede Log-Andeutung (anders als der website_policy-Fallback bei `:31`, der bei Bedarf in `extract` zumindest warnet). Konkrete Auslösung: Nutzer bricht mit /stop während einer laufenden Kette ab; es werden trotzdem alle Stufen aller URLs abgefragt, Anträge laufen in der bis zu ~15 s pro URL. Fix: im `except ImportError` eine einmalige `log.warning` ausgeben.

**3. Performance — `deepcopy` auch ohne Duplikat**
- Datei: `provider.py:133`
- `copy.deepcopy(done[u])` läuft für jede URL, auch wenn sie nur einmal vorkommt. Bei der maximalen Last (5 URLs mit langem Markdown) werden Content und Metadata komplett kopiert, ohne dass eine Aliasing-Gefahr besteht — nötig ist die Kopie nur für doppelt vorkommende URLs (S5). Fix: Kopie nur für Duplikate, z. B. Zähler über `urls` oder `urls.count(u) > 1`.

Keine Befunde zu Security: Keys landen nur gehasht in der Pausentabelle, im Log nur der Fehlercode, Redirects sind aus (`follow_redirects=False`), und ohne Blocklist wird fail-closed geleugnet (`:118-120`). Die breiten `except Exception`-Blöcke (`:74`, `:129`) sind dokumentiert (S6) und gemäß Vorgabe nicht gemeldet.
