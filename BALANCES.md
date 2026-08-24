# echorune — treasury balances

Cash only. Anyone can verify every number here directly on-chain;
nothing below depends on trusting us.

- treasury: `0xbc52B57679a732074456C0DD037380f6D0Ce3f57` (Base)
- basescan: https://basescan.org/address/0xbc52B57679a732074456C0DD037380f6D0Ce3f57
- snapshot: 2026-08-24 09:00:07 UTC, block 50386330

| asset | cumulative in | cumulative out | on-chain balance | reconciles |
|---|---|---|---|---|
| ETH | 0.080107 | 0.036602 | 0.039349 | NO — off by -4156415274585413 wei |
| USDC | 4.01 | 3.03 | 0.99 | yes |

`reconciles` is the identity `sum(in) - sum(out) == on-chain balance`,
compared as exact integers in wei — not rounded to the six decimals shown
above. When it fails the residual is printed in wei, so you can tell a
missing entry from a rounding artefact. Zero tolerance: gas, including the
OP-stack L1 data fee, is booked per transaction.

The balance is a snapshot at the block above and drifts as we spend gas;
check against that block, or regenerate: `python3 books/balances.py`.
A `NO` means our books missed a movement — that is a bug in us, and you
would see it here before we do.

Every outflow is a transaction hash. The line-item ledger (hours, rates,
ownership slices) is private; balances are not.

Verify the founding covenant instead of trusting this page:
`python3 ops/verify_covenant.py --version 1`
