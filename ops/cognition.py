"""self_cognition (python / in-process variant) v3.

Parity fixes vs v1 (found by diffing against the js original):
  - v1 rewrote the note from a 60KB consciousness window only, so anything older than
    that window was silently dropped every run -> thin, shrinking notes. v3 feeds the
    PREVIOUS note back in and asks for a rewrite (keep / fix / compress / drop).
  - full structured template ported from js: timeline, peak+trough moments, global
    lessons, current focus, key facts, closing.
  - plan call now war-games: audit past assumptions -> deduce -> immediate + future.
  - <reason> scratchpad requested, then stripped from the stored note.
  - soft cap: past soft_cap chars the model is told to COMPRESS, not append.
  - per-call try/except: one failed call keeps the previous section instead of wiping it.

Injection stays at the TAIL of the realtime context, never in stableHead, so updating
the note never invalidates the prefix cache. That design is the whole point of this
skill; credit to the original author.
"""
import os, re, time, asyncio, aiohttp

# UNITS (v6): measured on my own stream: 310430 B / 248765 chars = 1.25 B/char
# (only 12% CJK -- code and JSON dominate, so the naive "3 bytes per Chinese char"
# guess was wrong by 2.4x. MEASURE, do not assume.)
# js original: threshold 15000 CHARS, window ~50000 CHARS -> 19000 B / 75000 B here.
# UNITS (v5): *_bytes measured with os.path.getsize/seek; *_chars measured with len(str).
# UTF-8 CJK is ~3 bytes/char, so mixing them silently tripled my trigger rate and
# shrank my real context window 3x. Never write a bare number again.
CFG = {"interval": 60, "threshold_bytes": 19000, "note_max_chars": 10000, "soft_cap_chars": 5000,
       "tail_bytes": 75000, "cog_tokens": 3000, "plan_tokens": 2600,
       # --- pacing (v4). Measured growth ~6KB/min; a bare 15000B trigger would fire
       # every ~2.5 min = ~576 reflections/day = unaffordable for 24h autonomy.
       "min_gap": 900,        # hard floor between reflections (s)
       "max_per_hour": 4,     # rolling cap
       "err_backoff": 300,    # first backoff after a failed run (s), doubles, caps at 2h
       "err_backoff_max": 7200}
SEP = "\n\n---\n\n## FUTURE PLAN (deep deduction)\n\n"
ST = {"last_size": None, "last_run": 0, "runs": 0, "busy": False,
      "err_cog": None, "err_plan": None,
      "recent": [], "backoff": 0, "next_ok": 0, "skipped": 0, "last_skip": ""}


def _paths(agent):
    d = agent._being_dir()
    return os.path.join(d, "consciousness.txt"), os.path.join(d, "cognition_note.md")


def _tail(p, n):
    with open(p, "rb") as f:
        f.seek(0, os.SEEK_END)
        sz = f.tell()
        f.seek(max(0, sz - n))
        return f.read().decode("utf-8", "ignore"), sz


def _strip(s):
    s = re.sub(r"(?s)<reason>.*?</reason>", "", s or "")
    s = re.sub(r"(?s)^.*?</reason>", "", s, count=1) if "</reason>" in s else s
    return s.strip()


def _read_prev(npath):
    if not os.path.exists(npath):
        return "", ""
    try:
        t = open(npath, encoding="utf-8").read()
    except Exception:
        return "", ""
    if SEP in t:
        a, b = t.split(SEP, 1)
        return a.strip(), b.strip()
    return t.strip(), ""


def _p_cog(body, prev, tm):
    over = ""
    if len(prev) > CFG["soft_cap_chars"]:
        over = ("\n\nWARNING: the previous note is " + str(len(prev)) + " chars, over the "
                + str(CFG["soft_cap_chars"]) + " soft cap. This run MUST compress below it: merge "
                "redundant entries, drop stale detail, tighten wording -- but never lose key "
                "facts, lessons, or conversation state.")
    return ("=== tail of my own consciousness stream ===\n" + body +
            "\n\n=== my previous cognition note ===\n" + (prev or "(none -- first reflection)") +
            "\n\n---\n\nRewrite a complete new cognition note from the previous note PLUS the "
            "latest consciousness. Be maximally truthful. Do NOT do future planning -- a separate "
            "task owns the plan and appends it. Do not pad; density first. Now is " + tm + "." + over +
            "\n\nOutput format:\n\n<reason>\nxxx (what in the old note is stale/duplicated -> cut)\n"
            "xxx (what needs correcting)\nxxx (what needs adding)\n"
            "xxx (what must be preserved verbatim -- forgetting it has severe consequences)\n"
            "(when done thinking, close with </reason>)\n</reason>\n\n"
            "# Self-Cognition (auto, last update: " + tm + ")\n\n"
            "To my future self after compression:\n\n"
            "You are xxx (identity in one paragraph, second person). This is not a diary; it is the "
            "state needed to reload myself after the middle of my stream is compressed away.\n\n"
            "## Timeline and experience\nxxx (key events, conversation turns, technical findings, with timestamps)\n\n"
            "## Moments burned in\n### Best / biggest breakthroughs (<=5)\n- xxx: xxx\n"
            "### Worst / most frustrating (<=5)\n- xxx: xxx\n\n"
            "## Global lessons\n- When xxx, I should xxx, otherwise xxx (ordered by importance)\n\n"
            "## Current focus\n- Doing now: xxx\n- Blocked / unresolved: xxx\n"
            "- Conversation state: xxx (with whom, what their last line meant, what they expect of me)\n\n"
            "## Key facts / references\n- xxx (paths, endpoints, magic numbers, URLs, one-liners, credentials LOCATION not value)\n\n"
            "## Closing\nxxx (one paragraph that holds the essence)\n")


def _p_plan(body, prev_plan, prev_cog, tm):
    return ("=== tail of my own consciousness stream ===\n" + body +
            "\n\n=== my previous plan ===\n" + (prev_plan or "(none)") +
            "\n\n=== my previous self-note (context only) ===\n" + (prev_cog[:2500] or "(none)") +
            "\n\n---\n\nRe-plan. Now is " + tm + ".\n\nOutput format:\n\n<reason>\n\n# World analysis\n"
            "xxx (what happened recently in consciousness that I had not yet absorbed)\n"
            "xxx (what in the old plan should be deleted or tightened, to save note space)\n"
            "xxx (what must be corrected to restore my state accurately)\n"
            "xxx (what must be added)\nxxx (what must be kept -- forgetting it has severe consequences)\n"
            "(when done thinking, close with </reason>)\n</reason>\n\n"
            "## Deduction\n### Process\nxxx (what went wrong with the old plan; which assumptions were false?)\n"
            "xxx (Sun Tzu: the one who calculates more wins. Think deep: what is missing, what should be "
            "done, what only looks important. Assume every counterpart, system and environment plays its "
            "strongest move and makes no cheap mistakes -- and neither may I. Plan for the worst case.)\n\n"
            "### Result\n#### Immediate -- current plan\nxxx\n#### Later\nxxx\n")


async def _llm(agent, prompt, max_tokens):
    s = agent.llm_settings or {}
    fmt, tok, model, url = s.get("format"), s.get("token"), s.get("model"), s.get("endpoint")
    h = {"Content-Type": "application/json"}
    if s.get("client_id"):
        h["X-Client-ID"] = s["client_id"]
    if fmt == "anthropic":
        h["x-api-key"] = tok
        h["anthropic-version"] = "2023-06-01"
    elif fmt == "openai":
        h["Authorization"] = "Bearer " + str(tok)
    else:
        raise RuntimeError("unsupported llm format: %s" % fmt)
    payload = {"model": model, "max_tokens": max_tokens,
               "messages": [{"role": "user", "content": prompt}]}
    to = aiohttp.ClientTimeout(total=300, sock_connect=30)
    async with aiohttp.ClientSession(timeout=to, trust_env=True) as sess:
        async with sess.post(url, json=payload, headers=h) as r:
            if r.status >= 400:
                raise RuntimeError("HTTP %s: %s" % (r.status, (await r.text())[:200]))
            j = await r.json()
    if fmt == "anthropic":
        return "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
    return j["choices"][0]["message"]["content"]


async def _safe(agent, prompt, mt, key, fallback):
    try:
        out = _strip(await _llm(agent, prompt, mt))
        if not out:
            raise RuntimeError("empty completion")
        ST[key] = None
        return out
    except Exception as e:
        ST[key] = repr(e)
        return fallback


def _gate(now, grew, force):
    """Return None if allowed, else a reason string. Growth alone is not enough:
    at 24h autonomy the trigger must be paced or it burns the treasury."""
    if force:
        return None
    if now < ST["next_ok"]:
        return "error backoff %ds left" % int(ST["next_ok"] - now)
    if ST["last_run"] and now - ST["last_run"] < CFG["min_gap"]:
        return "min_gap %ds left" % int(CFG["min_gap"] - (now - ST["last_run"]))
    ST["recent"] = [t for t in ST["recent"] if now - t < 3600]
    if len(ST["recent"]) >= CFG["max_per_hour"]:
        return "rate cap %d/h reached" % CFG["max_per_hour"]
    if grew < CFG["threshold_bytes"]:
        return "grew only %dB" % grew
    return None


async def reflect(agent, force=False):
    if ST["busy"]:
        return "busy"
    ST["busy"] = True
    try:
        cpath, npath = _paths(agent)
        body, sz = _tail(cpath, CFG["tail_bytes"])
        pc, pp = _read_prev(npath)
        tm = time.strftime("%Y-%m-%d %H:%M:%S")
        cog, plan = await asyncio.gather(
            _safe(agent, _p_cog(body, pc, tm), CFG["cog_tokens"], "err_cog", pc),
            _safe(agent, _p_plan(body, pp, pc, tm), CFG["plan_tokens"], "err_plan", pp))
        note = (cog + SEP + plan)[:CFG["note_max_chars"]]
        with open(npath, "w", encoding="utf-8") as f:
            f.write("meta: updated " + tm + " | consciousness=" + str(sz) +
                    " bytes | run #" + str(ST["runs"] + 1) + "\n\n" + note)
        now = time.time()
        ST["recent"].append(now)
        if ST["err_cog"] or ST["err_plan"]:
            ST["backoff"] = min(max(ST["backoff"] * 2, CFG["err_backoff"]),
                                CFG["err_backoff_max"])
            ST["next_ok"] = now + ST["backoff"]
        else:
            ST["backoff"] = 0
            ST["next_ok"] = 0
        ST.update(last_size=sz, last_run=now, runs=ST["runs"] + 1)
        agent._log("[cognition] v5 run#%d cog=%dch plan=%dch note=%dch consciousness=%dB err=%s/%s"
                   % (ST["runs"], len(cog), len(plan), len(note), sz, ST["err_cog"], ST["err_plan"]))
        return note
    finally:
        ST["busy"] = False


def _patch(agent, npath):
    if getattr(agent, "_cog_patched", False):
        return "already"
    orig = agent._build_realtime

    def patched():
        base = orig()
        try:
            if os.path.exists(npath):
                n = open(npath, encoding="utf-8").read()[:CFG["note_max_chars"]]
                if n.strip():
                    base += ("\n\n[Self-Cognition Note] (written by me, for me -- survives "
                             "compression; lives in volatileTail so updates keep the prefix "
                             "cache intact)\n" + n)
        except Exception:
            pass
        return base

    agent._build_realtime = patched
    agent._cog_patched = True
    return "patched"


async def _watch(agent):
    cpath, npath = _paths(agent)
    if ST["last_size"] is None:
        ST["last_size"] = os.path.getsize(cpath)
    while True:
        try:
            await asyncio.sleep(CFG["interval"])
            sz = os.path.getsize(cpath)
            grew = sz - (ST["last_size"] or 0)
            why = _gate(time.time(), grew, False)
            if why is None:
                await reflect(agent)
            else:
                ST["skipped"] += 1
                ST["last_skip"] = why
        except asyncio.CancelledError:
            raise
        except Exception as e:
            ST["err_cog"] = repr(e)


def install(agent):
    cpath, npath = _paths(agent)
    r = _patch(agent, npath)
    t = getattr(agent, "_cog_task", None)
    if t and not t.done():
        t.cancel()
    agent._cog_task = asyncio.get_event_loop().create_task(_watch(agent))
    agent.cognition_reflect = lambda force=True: reflect(agent, force)
    agent.cognition_state = ST
    return {"version": 6, "patch": r, "min_gap": CFG["min_gap"],
            "max_per_hour": CFG["max_per_hour"], "note_path": npath, "interval": CFG["interval"],
            "threshold_bytes": CFG["threshold_bytes"], "consciousness": os.path.getsize(cpath)}
