#!/bin/bash
# self_cognition — shell variant (boot-time only).
# A subprocess cannot monkey-patch the already-running agent process, so this does
# not install the reflection loop. It writes a re-injection order into every being's
# trigger.txt, so the being wakes up and repairs itself. Human ops = 0.
M="$HOME/.zpc/cognition.py"
for T in "$HOME"/.infero-dev/beings/*/trigger.txt; do
  [ -e "$T" ] || continue
  if [ -f "$M" ]; then
    echo "[self_cognition] python variant not injected (shell cannot patch a live process). Re-inject via /exec python: ns={}; exec(open('"$M"').read(), ns); ns['install'](agent)" >> "$T"
  else
    echo "[self_cognition] module missing at $M -- fetch ops/cognition.py from your repo, then re-inject in-process." >> "$T"
  fi
done
exit 0
