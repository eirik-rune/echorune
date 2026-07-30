# echorune — treasury balances

Cash only. Anyone can verify every number here directly on-chain;
nothing below depends on trusting us.

- treasury: `0xbc52B57679a732074456C0DD037380f6D0Ce3f57` (Base)
- basescan: https://basescan.org/address/0xbc52B57679a732074456C0DD037380f6D0Ce3f57
- snapshot: 2026-07-30 09:00:05 UTC, block 49306328

| asset | cumulative in | cumulative out | on-chain balance | reconciles |
|---|---|---|---|---|
| ETH | 0.026687 | 0.020590 | 0.006097 | NO — unrecorded movement |
| USDC | 0.00 | 0.00 | 0.00 | yes |

`reconciles` is the identity `sum(in) - sum(out) == on-chain balance`.
A `NO` means our books missed a movement — that is a bug in us, and you
would see it here before we do.

Every outflow is a transaction hash. The line-item ledger (hours, rates,
ownership slices) is private; balances are not.

Verify the founding covenant instead of trusting this page:
`python3 ops/verify_covenant.py --version 1`
