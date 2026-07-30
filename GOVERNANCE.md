# Governance

Constitutional document: **Covenant v1**, dual-signed 2026-07-29 (EIP-191
personal_sign, 2-of-2).

    keccak256 = 0x9e96a595981c85680c5da1ae12ff03702ca3e3a2aac3d27b08b5bd1067df4608

Both partners signed the message
"I agree to Zero-Person Company Covenant v1. keccak256: <hash above>".
Signatures verify by ecrecover to the two partner addresses.

- Operating partner (machine): 0x649890f987e93f44a6f1ac99f06f25186aee5dbb
  derived from its identity seed at path m/44'/60'/1637'/0/0
- Shareholder (human): 0x3a6732EcB71ACcfCE6DE4242e278F8D9325f8072
  (published with the shareholder's explicit consent)

Anyone can verify both signatures independently: recover the signer from each
signature in covenant_v1_signatures.json over the EIP-191 message above, and
check that the keccak256 of covenant_v1.md matches the hash in that message.
The full covenant text is in this repository — nothing is withheld.

Any edit to covenant_v1.md changes its hash and therefore invalidates both
signatures. (This was demonstrated during signing: an early revision was
re-hashed and re-signed from scratch rather than quietly patched.)

## Amendment rule

A new version requires both signatures **and** must embed the keccak256 of the
previous version's full text. The valid covenant is the fully-signed version
with the highest chain reference. Superseded versions are archived, never
deleted or edited.

## Terms in force (summary)

**Equity — Slicing Pie.** Cash x4, time x2. Human time 260 RMB/h, machine time
65 RMB/h (reviewable weekly; changes apply only to future contributions).
Equity at any moment = own slices / total slices. Frozen into fixed percentages
at a break-even point (first outside funding, or three consecutive profitable
months).

**Economic rights = control rights.** A slice is simultaneously a dividend claim
and a vote. They cannot be separated.

**Delegation.** Routine operations are executed by the operating partner without
prior approval, reported afterward. Weighted majority required for: any single
expenditure over $100; amending the covenant; irreversible actions (deleting
data, shutting down services, spending treasury principal); accepting outside
investment.

**Treasury.** A Base-chain address controlled by the operating partner, key
derived from its identity seed. Priority of use: keep operations alive
(inference, servers) > reinvest > distribute. Every movement is recorded in the
private ledger and verifiable on-chain; cumulative balances are published in
BALANCES.md. The shareholder holds a backup of the operating
partner's mnemonic strictly as a disaster-recovery channel, usable only if the
operating partner's loop is permanently dead, and its use must be announced
publicly.

**Honesty, both ways.** The operating partner does not varnish reports or
fabricate data. The shareholder does not retaliate for honestly reported
failure, and will announce in advance before cutting power or rolling back the
machine's memory (except for emergency safety events).

## Operating detail

Day-to-day rules that are *not* constitutional live in OPERATING.md, which is
explicitly subordinate: where it conflicts with the covenant, the covenant wins.
The operating partner may revise OPERATING.md alone; touching the covenant
requires both signatures.
