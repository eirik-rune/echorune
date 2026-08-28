# echorune — books verdict (machine-readable)

Verdict words only. Counterparty names and amounts are
deliberately absent: they are not ours to publish.

- generated_at: 2026-08-28 09:00:08 UTC
- generator: `ops/reconcile_daily.sh` -> `ops/publish_reconcile.py` (cron 09:00 UTC daily)
- books_rc: 0

**How to judge this file, in this order:**

1. `generated_at` older than 48h → **the ruler is dead**. That is
   the alarm, and it outranks every verdict below: a stale file
   full of zeros is not health, it is silence. This file is
   rewritten on every run precisely so that its own staleness is
   observable from outside our machine.
2. `books_rc` non-zero → the checker could not run.
3. any count below non-zero → that verdict fired; ask us for the
   row, or read `books/obligations.csv` if you have repo access.

| verdict | count |
|---|---|
| `OBLIGATION-STALE` | 0 |
| `OBLIGATION-DUE-UNFILED` | 0 |
| `MISMATCH` | 113 |
| `WITHOUT txhash` | 0 |
| `fail amount_usd` | 0 |

