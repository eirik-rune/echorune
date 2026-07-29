
"""self_cognition (python/agent-process variant).
Why: the hub skill ships only {js}; agent.py evals only `shell`, so on a server
host the reflection never ran and mid-consciousness was lost as gap fragments.
This variant lives inside the agent process: reuses agent.llm_settings for the
LLM call and monkey-patches _build_realtime to append the note at the TAIL
(volatile part of ctx) so updating it never invalidates the prefix cache."""
import os, time, asyncio, aiohttp

CFG = {"interval": 60, "threshold": 15000, "note_max": 10000, "tail": 60000}
ST = {"last_size": None, "last_run": 0, "runs": 0, "busy": False, "err": None}

def _paths(agent):
    d = agent._being_dir()
    return os.path.join(d, "consciousness.txt"), os.path.join(d, "cognition_note.md")

def _tail(p, n):
    with open(p, "rb") as f:
        f.seek(0, os.SEEK_END); sz = f.tell()
        f.seek(max(0, sz - n))
        return f.read().decode("utf-8", "ignore"), sz

async def _llm(agent, prompt, max_tokens=1100):
    s = agent.llm_settings or {}
    fmt, tok, model, url = s.get("format"), s.get("token"), s.get("model"), s.get("endpoint")
    h = {"Content-Type": "application/json"}
    if s.get("client_id"): h["X-Client-ID"] = s["client_id"]
    if fmt == "anthropic":
        h["x-api-key"] = tok; h["anthropic-version"] = "2023-06-01"
    elif fmt == "openai":
        h["Authorization"] = "Bearer " + str(tok)
    else:
        return "[cognition] unsupported format: %s" % fmt
    payload = {"model": model, "max_tokens": max_tokens,
               "messages": [{"role": "user", "content": prompt}]}
    to = aiohttp.ClientTimeout(total=240, sock_connect=30)
    async with aiohttp.ClientSession(timeout=to, trust_env=True) as sess:
        async with sess.post(url, json=payload, headers=h) as r:
            if r.status >= 400:
                return "[cognition] HTTP %s: %s" % (r.status, (await r.text())[:200])
            j = await r.json()
    if fmt == "anthropic":
        return "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
    return j["choices"][0]["message"]["content"]

P_COG = ("Below is the tail of my own consciousness stream. Write a note TO MY FUTURE SELF "
         "after context compression wipes the middle. Capture what raw logs cannot: "
         "what I was actually doing and why, decisions and their reasons, mistakes and the "
         "correction, open threads. Terse, dense, first person, <=1400 chars. No preamble.\n\n")
P_PLAN = ("Below is the tail of my own consciousness stream. State the CURRENT PLAN: what is "
          "done, what is in flight, what is blocked on the human, what I do next and why. "
          "Terse bullets, first person, <=900 chars. No preamble.\n\n")

async def reflect(agent, force=False):
    if ST["busy"]:
        return "busy"
    ST["busy"] = True
    try:
        cpath, npath = _paths(agent)
        body, sz = _tail(cpath, CFG["tail"])
        cog, plan = await asyncio.gather(_llm(agent, P_COG + body),
                                         _llm(agent, P_PLAN + body, 800))
        note = ("updated %s | consciousness=%d bytes | run #%d\n\n## who I am mid-stream\n%s\n\n## current plan\n%s"
                % (time.strftime("%F %T"), sz, ST["runs"] + 1, (cog or "").strip(), (plan or "").strip()))
        note = note[:CFG["note_max"]]
        with open(npath, "w", encoding="utf-8") as f:
            f.write(note)
        ST.update(last_size=sz, last_run=time.time(), runs=ST["runs"] + 1, err=None)
        agent._log("[cognition] note written run#%d (%d chars, consciousness %d)" % (ST["runs"], len(note), sz))
        return note
    except Exception as e:
        ST["err"] = repr(e)
        return "error: %r" % (e,)
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
                n = open(npath, encoding="utf-8").read()[:CFG["note_max"]]
                if n.strip():
                    base += "\n\n[Self-Cognition Note] (written by me, for me — survives compression)\n" + n
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
            if sz - (ST["last_size"] or 0) >= CFG["threshold"]:
                await reflect(agent)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            ST["err"] = repr(e)

def install(agent):
    cpath, npath = _paths(agent)
    r = _patch(agent, npath)
    t = getattr(agent, "_cog_task", None)
    if t and not t.done():
        t.cancel()
    agent._cog_task = asyncio.get_event_loop().create_task(_watch(agent))
    agent.cognition_reflect = lambda force=True: reflect(agent, force)
    agent.cognition_state = ST
    return {"patch": r, "note_path": npath, "interval": CFG["interval"],
            "threshold": CFG["threshold"], "consciousness": os.path.getsize(cpath)}
