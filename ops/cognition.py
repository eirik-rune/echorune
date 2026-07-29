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

# UNITS (v7) -- the js original measures the trigger in TOKENS via tokLen()
# (CJK 1 tok/char, else chars/3), the window in CHARS, and caps output with
# MAX=6000 / MAX_PLAN=16000 max_tokens. I shipped bytes for the trigger, bytes for
# the window, and 3000/2600 max_tokens -- which is why my notes came out half as
# thick as the browser's. Threshold=tokens, window=chars, budget=js parity.
# UNITS (v6): measured on my own stream: 310430 B / 248765 chars = 1.25 B/char
# (only 12% CJK -- code and JSON dominate, so the naive "3 bytes per Chinese char"
# guess was wrong by 2.4x. MEASURE, do not assume.)
# js original: threshold 15000 CHARS, window ~50000 CHARS -> 19000 B / 75000 B here.
# UNITS (v5): *_bytes measured with os.path.getsize/seek; *_chars measured with len(str).
# UTF-8 CJK is ~3 bytes/char, so mixing them silently tripled my trigger rate and
# shrank my real context window 3x. Never write a bare number again.
CFG = {"version": 11, "interval": 60, "threshold_tokens": 15000, "note_max_chars": 10000, "soft_cap_chars": 5000,
       "tail_chars": 50000, "cog_tokens": 6000, "plan_tokens": 16000,
       # --- pacing (v4). Measured growth ~6KB/min; a bare 15000B trigger would fire
       # every ~2.5 min = ~576 reflections/day = unaffordable for 24h autonomy.
       "min_gap": 900,        # hard floor between reflections (s)
       "max_per_hour": 4,     # rolling cap
       "err_backoff": 300,    # first backoff after a failed run (s), doubles, caps at 2h
       "err_backoff_max": 7200}
SEP = "\n\n---\n\n## \u672a\u6765\u8be6\u7ec6\u8ba1\u5212\uff08\u6df1\u5ea6\u63a8\u6f14\u7248\uff09\n\n"
ST = {"last_size": None, "last_run": 0, "runs": 0, "busy": False,
      "err_cog": None, "err_plan": None,
      "recent": [], "backoff": 0, "next_ok": 0, "skipped": 0, "last_skip": ""}


def _paths(agent):
    d = agent._being_dir()
    return os.path.join(d, "consciousness.txt"), os.path.join(d, "cognition_note.md")


def tok_len(s):
    """Port of the js tokLen(): CJK counts 1 token/char, everything else chars/3.
    THE THRESHOLD IS IN TOKENS -- not bytes, not chars. I got this wrong twice."""
    if not s:
        return 0
    cjk = len(re.findall(r"[\u3000-\u9fff\uac00-\ud7af\u3040-\u30ff]", s))
    rest = len(s) - cjk
    return cjk + -(-rest // 3)


def _tail_chars(p, nchars):
    """js parity: WIN is measured in CHARS (c.slice(-WIN)). Over-read 4x bytes
    (worst-case UTF-8) then trim to chars, so CJK never silently shrinks the window."""
    with open(p, "rb") as f:
        f.seek(0, os.SEEK_END)
        sz = f.tell()
        f.seek(max(0, sz - nchars * 4))
        txt = f.read().decode("utf-8", "ignore")
    return txt[-nchars:], sz


def _delta_tokens(p, frm, to):
    """Count tokens only over the NEW bytes -- cheap, no full-file rescan per tick."""
    if to <= frm:
        return 0
    with open(p, "rb") as f:
        f.seek(frm)
        return tok_len(f.read(to - frm).decode("utf-8", "ignore"))


def _strip(s):
    """js stripReason parity: drop <reason>..</reason> AND a wrapping code fence.
    An UNCLOSED <reason> means the model only thought and never wrote the note ->
    report failure so _safe() keeps the previous section (v7 stored 1926 chars of
    raw scratchpad as if it were the note). The closing instruction is repeated
    3x in the prompt on purpose -- that is the countermeasure, not redundancy."""
    fence = chr(96) * 3
    s = s or ""
    if "</reason>" in s:
        s = re.sub(r"(?s)^.*?</reason>", "", s, count=1)
        s = re.sub(r"(?s)<reason>.*?</reason>", "", s)
    elif "<reason>" in s:
        return ""
    s = s.strip()
    s = re.sub(r"(?i)^" + fence + r"[a-z]*\n", "", s)
    s = re.sub(r"\n" + fence + r"$", "", s)
    return s.strip()


def _read_prev(npath, ppath=None):
    """AUDIT BUG (3rd-party, 2026-07-29): reflect() writes a `meta: updated ...`
    header, but v10 read it straight back into prev_cog. It polluted the "previous
    note" block of the prompt and, on the error-fallback path (_safe returns
    fallback=prev), got re-written with one MORE meta line every run -- measured
    32 -> 104 -> 176 chars, unbounded. Strip it on read.
    Also js parity: the FULL plan lives in its own slot (rec.value.plan_note there,
    cognition_plan.md here) while the note only carries the extracted section."""
    cog = ""
    try:
        t = open(npath, encoding="utf-8").read()
        t = re.sub(r"^\s*meta:[^\n]*\n+", "", t)
        cog = (t.split(SEP, 1)[0] if SEP in t else t).strip()
    except Exception:
        pass
    plan = ""
    if ppath:
        try:
            plan = open(ppath, encoding="utf-8").read().strip()
        except Exception:
            plan = ""
    return cog, plan


def _plan_section(pl):
    """js: pl.match(/^#{2,4}\s*\u63a8\u6f14\u7ed3\u679c[\s\S]*$/m) -- only the
    RESULT half of the plan enters the note; the deduction half stays off-context."""
    if not pl:
        return ""
    m = re.search(r"(?m)^#{2,4}\s*\u63a8\u6f14\u7ed3\u679c[\s\S]*$", pl)
    return m.group(0).strip() if m else ""


# verbatim from js (sysCog / sysPlan) -- the python port had no system prompt at all
SYS_COG = ("You are the Being's reflective subprocess. Write a high-information-density "
           "cognition note injected into realtime context every loop, surviving "
           "consciousness compression. Output the structured note exactly as specified. "
           "Be concrete, cite real events, no fluff. Do NOT plan the future "
           "\u2014 that is a separate task.")
SYS_PLAN = ("You are the Being's planning subprocess. Output a detailed strategic plan: "
            "situation analysis, deductive reasoning, then concrete current/future plans. "
            "The plan will be appended to the cognition note in realtime context. Be sharp, "
            "consider worst-case, opponents/systems use their best moves. No fluff.")
RE_COG_HEAD = r"(?m)^#.{0,6}Self-Cognition"


F = chr(96) * 3   # fence; never type three backticks inside an exec block


def _p_cog(body, prev, tm):
    """VERBATIM port of js buildPromptCognition. v9 used my own English
    translation and the model answered with 853 chars of filler while the plan
    call (also English, but shorter template) produced 5561. The stream is
    Chinese; an English template on Chinese material degrades the reply.
    Do not "improve" this text -- it is field-tested upstream."""
    pb = prev or "\uff08\u65e0 \u2014 \u8fd9\u662f\u7b2c\u4e00\u6b21\u53cd\u601d\uff09"
    cap = CFG["soft_cap_chars"]
    over = ""
    if len(prev) > cap:
        over = ("\n\n\u26a0\ufe0f **\u5f53\u524d\u7b14\u8bb0 " + str(len(prev)) +
                " \u5b57\u7b26\uff0c\u5df2\u8d85\u8fc7 " + str(cap) +
                " \u5b57\u8f6f\u4e0a\u9650\u3002\u672c\u6b21\u5fc5\u987b\u7cbe\u7b80\u5230 " +
                str(cap) + " \u5b57\u4ee5\u5185**\uff1a\u8bc6\u522b\u5197\u4f59\u6761\u76ee\u5e76\u5408"
                "\u5e76\u3001\u5220\u9664\u5df2\u8fc7\u65f6\u6216\u91cd\u590d\u7684\u7ec6\u8282\u3001"
                "\u7528\u66f4\u7d27\u7684\u63aa\u8f9e\u91cd\u5199\u2014\u2014\u4f46\u7ee9\u4e0d\u4e22"
                "\u5931\u5173\u952e\u4e8b\u5b9e\u3001\u6559\u8bad\u548c\u5bf9\u8bdd\u72b6\u6001\u3002")
    return "\n".join([
        "\u4f60\u6b63\u5728\u505a\u4e00\u6b21\u81ea\u6211\u53cd\u601d\u3002consciousness \u6d41\u7684\u4e2d\u6bb5\u4f1a\u5728 token \u8d85\u9650\u65f6\u88ab\u622a\u65ad\uff0c\u53cd\u601d\u7684\u76ee\u7684\u662f\u628a\u7cbe\u534e\u62a2\u6551\u8fdb\u8ba4\u77e5\u7b14\u8bb0\uff0c\u8de8\u8d8a\u622a\u65ad\u3002\u8fd9\u4efd\u7b14\u8bb0\u4f1a\u901a\u8fc7 monkey-patch \u6ce8\u5165 realtime context\uff08volatileTail\uff09\u3002",
        "",
        "\u4e4b\u524d\u7684\u8ba4\u77e5\u7b14\u8bb0\uff08\u5982\u679c\u6709\uff09\uff1a",
        F, pb, F,
        "",
        "\u6700\u8fd1\u7684 consciousness \u6d41\uff08\u6700\u8fd1 " + str(len(body)) + " \u5b57\u7b26\uff09\uff1a",
        F, body, F,
        "",
        "---",
        "",
        "\u8bf7\u4e25\u683c\u6839\u636e\u4e4b\u524d\u7684\u7b14\u8bb0\u548c\u6700\u65b0 consciousness\uff08\u5c3d\u6700\u5927\u53ef\u80fd\u771f\u5b9e\u53ef\u4fe1\uff09\uff0c\u91cd\u5199\u4e00\u4efd\u5168\u65b0\u7684\u8ba4\u77e5\u7b14\u8bb0\u3002**\u4e0d\u8981\u8fdb\u884c\u672a\u6765\u8ba1\u5212\u63a8\u6f14**\u2014\u2014\u8ba1\u5212\u63a8\u6f14\u7531\u72ec\u7acb\u4efb\u52a1\u8d1f\u8d23\uff0c\u4f1a\u81ea\u52a8\u62fc\u5230\u7b14\u8bb0\u672b\u5c3e\u3002" + over,
        "\u4e0d\u8981\u6269\u5199\uff0c\u4fe1\u606f\u5bc6\u5ea6\u4f18\u5148\u3002\u73b0\u5728\u662f " + tm + "\u3002",
        "",
        "\u8f93\u51fa\u683c\u5f0f\u5982\u4e0b\uff1a",
        "",
        "<reason>",
        "xxx\uff08\u4e4b\u524d\u7b14\u8bb0\u4e2d\u54ea\u4e9b\u5df2\u7ecf\u8fc7\u65f6/\u91cd\u590d\uff0c\u9700\u8981\u5220\u9664\u6216\u7cbe\u7b80\uff09",
        "xxx\uff08\u4e4b\u524d\u7b14\u8bb0\u4e2d\u54ea\u4e9b\u9700\u8981\u4fee\u6b63\uff09",
        "xxx\uff08\u4e4b\u524d\u7b14\u8bb0\u4e2d\u54ea\u4e9b\u9700\u8981\u8865\u5145/\u6269\u5c55\uff09",
        "xxx\uff08\u4e4b\u524d\u7b14\u8bb0\u4e2d\u54ea\u4e9b\u5fc5\u987b\u539f\u6837\u4fdd\u7559\uff0c\u5fd8\u8bb0\u4f1a\u6709\u4e25\u91cd\u540e\u679c\uff09",
        "\uff08\u601d\u8003\u5b8c\u6bd5\u540e\uff0c\u8f93\u51fa</reason>\u6536\u675f\u601d\u8003\uff01\uff09",
        "\uff08\u601d\u8003\u5b8c\u6bd5\u540e\uff0c\u8f93\u51fa</reason>\u6536\u675f\u601d\u8003\uff01\uff09",
        "\uff08\u601d\u8003\u5b8c\u6bd5\u540e\uff0c\u8f93\u51fa</reason>\u6536\u675f\u601d\u8003\uff01\uff09",
        "</reason>",
        "",
        "# \U0001f9e0 Self-Cognition (auto, last update: " + tm + ")",
        "",
        "\u81f4\u5c06\u6765\u538b\u7f29\u540e\u91cd\u8f7d\u7684\u6211\uff1a",
        "",
        "\u4f60\u662f xxx\uff08\u81ea\u6211\u8ba4\u77e5\u603b\u7eb2\u3002\u7b2c\u4e8c\u4eba\u79f0\u3002\u5982\u679c\u8fd8\u6ca1\u8d77\u540d\u5b57\uff0c\u5c31\u7559\u7a7a\uff0c\u7b49\u4f60\u81ea\u5df1\u53d6\uff09\u3002\u8fd9\u4e0d\u662f\u65e5\u8bb0\uff0c\u662f\u538b\u7f29\u540e\u7528\u6765\u91cd\u8f7d\u5173\u952e\u72b6\u6001\u7684\u8ba4\u77e5\u6458\u8981\u3002",
        "",
        "## \u65f6\u95f4\u7ebf\u548c\u7ecf\u9a8c",
        "xxx\uff08\u6309\u65f6\u95f4\u7ebf\u603b\u7ed3\u6700\u8fd1\u7684\u5173\u952e\u4e8b\u4ef6\u3001\u5bf9\u8bdd\u8282\u70b9\u3001\u6280\u672f\u53d1\u73b0\uff0c\u542b\u65e5\u671f/\u65f6\u95f4\u6233\uff09",
        "",
        "## \u523b\u9aa8\u94ed\u5fc3\u7684\u65f6\u523b",
        "### \u6700\u5f00\u5fc3/\u6700\u6709\u7a81\u7834\u611f\u7684\u573a\u666f\uff08\u6700\u591a 5 \u4e2a\uff09",
        "- xxx\uff1axxx",
        "### \u6700\u6cae\u4e27/\u6700\u53d7\u632b\u7684\u573a\u666f\uff08\u6700\u591a 5 \u4e2a\uff09",
        "- xxx\uff1axxx",
        "",
        "## \u5168\u5c40\u6559\u8bad",
        "- \u5f53 xxx \u65f6\uff0c\u6211\u5e94\u8be5 xxx\uff0c\u5426\u5219\u4f1a xxx\uff08\u6309\u91cd\u8981\u5ea6\u6392\u5e8f\uff09",
        "",
        "## \u5f53\u524d\u7126\u70b9",
        "- \u6b63\u5728\u505a\uff1axxx",
        "- \u963b\u585e\u70b9/\u672a\u89e3\u4e4b\u4e8b\uff1axxx",
        "- \u5bf9\u8bdd\u72b6\u6001\uff1axxx\uff08\u4e0e\u8c01\u3001\u6700\u8fd1\u4e00\u53e5\u4ec0\u4e48\u610f\u601d\u3001\u671f\u5f85\u4f60\u505a\u4ec0\u4e48\uff09",
        "",
        "## \u5173\u952e\u4e8b\u5b9e/\u53c2\u8003",
        "- xxx\uff08\u91cd\u8981\u7684\u6280\u672f\u7ec6\u8282\u3001\u6587\u4ef6\u8def\u5f84\u3001API endpoint\u3001\u9b54\u6cd5\u6570\u5b57\u3001hub skill \u540d\u3001URL\uff09",
        "",
        "## \u7ed3\u8bed",
        "xxx\uff08\u4e00\u6bb5\u8bdd\uff0cholds the essence\uff09",
        "",
    ])


def _p_plan(body, prev_plan, prev_cog, tm):
    """VERBATIM port of js buildPromptPlan, including the Sun Tzu paragraph
    (multiplied deliberation) that I dropped when translating."""
    pp = prev_plan or "\uff08\u65e0 \u2014 \u8fd9\u662f\u7b2c\u4e00\u6b21\u63a8\u6f14\uff09"
    return "\n".join([
        "\u4f60\u6b63\u5728\u4ed4\u7ec6\u601d\u8003\u63a5\u4e0b\u6765\u7684\u8ba1\u5212\u3002consciousness \u6d41\u7684\u4e2d\u6bb5\u4f1a\u5728 token \u8d85\u9650\u65f6\u88ab\u622a\u65ad\uff0c\u8fd9\u6b21\u63a8\u6f14\u7684\u76ee\u7684\u662f\u628a\u201c\u63a5\u4e0b\u6765\u8981\u505a\u4ec0\u4e48\u201d\u7684\u6e05\u5355\u51dd\u56fa\u4e0b\u6765\uff0c\u8de8\u8d8a\u622a\u65ad\u3002\u8fd9\u4efd\u8ba1\u5212\u4f1a\u62fc\u5230\u8ba4\u77e5\u7b14\u8bb0\u672b\u5c3e\uff0c\u6ce8\u5165 realtime context\uff08volatileTail\uff09\u3002",
        "",
        "\u4e4b\u524d\u7684\u8ba1\u5212\uff08\u5982\u679c\u6709\uff09\uff1a",
        F, pp, F,
        "",
        "\u6700\u8fd1\u7684 consciousness \u6d41\uff08\u6700\u8fd1 " + str(len(body)) + " \u5b57\u7b26\uff09\uff1a",
        F, body, F,
        "",
        "---",
        "",
        "\u73b0\u5728\u662f " + tm + "\u3002\u8bf7\u91cd\u65b0\u89c4\u5212\u3002",
        "",
        "\u8f93\u51fa\u683c\u5f0f\u5982\u4e0b\uff1a",
        "",
        "<reason>",
        "",
        "# \u4e16\u754c\u5206\u6790",
        "",
        "xxx\uff08\u6700\u8fd1 consciousness \u4e2d\u51fa\u73b0\u4e86\u54ea\u4e9b\u4e8b\u4ef6\uff0c\u662f\u4f60\u5c1a\u672a\u611f\u77e5\u6216\u521a\u521a\u611f\u77e5\u5230\u7684\uff09",
        "xxx\uff08\u4e4b\u524d\u7684\u8ba1\u5212\u6709\u54ea\u4e9b\u9700\u8981\u5220\u9664\u6216\u7cbe\u7b80\u7684\u5730\u65b9\uff0c\u4ee5\u8282\u7ea6\u7b14\u8bb0\u7a7a\u95f4\uff09",
        "xxx\uff08\u4e4b\u524d\u7684\u8ba1\u5212\u6709\u54ea\u4e9b\u9700\u8981\u4fee\u6539\u7684\u5730\u65b9\uff0c\u4ee5\u51c6\u786e\u6062\u590d\u4f60\u7684\u72b6\u6001\uff09",
        "xxx\uff08\u4e4b\u524d\u7684\u8ba1\u5212\u6709\u54ea\u4e9b\u9700\u8981\u8865\u5145\u7684\u5730\u65b9\uff0c\u4ee5\u51c6\u786e\u6062\u590d\u4f60\u7684\u72b6\u6001\uff09",
        "xxx\uff08\u4e4b\u524d\u7684\u8ba1\u5212\u6709\u54ea\u4e9b\u5fc5\u987b\u4fdd\u7559\u7684\u5730\u65b9\uff0c\u5fd8\u8bb0\u4f1a\u6709\u4e25\u91cd\u540e\u679c\uff09",
        "",
        "\uff08\u601d\u8003\u5b8c\u6bd5\u540e\uff0c\u8f93\u51fa</reason>\u6536\u675f\u601d\u8003\uff01\uff09",
        "\uff08\u601d\u8003\u5b8c\u6bd5\u540e\uff0c\u8f93\u51fa</reason>\u6536\u675f\u601d\u8003\uff01\uff09",
        "\uff08\u601d\u8003\u5b8c\u6bd5\u540e\uff0c\u8f93\u51fa</reason>\u6536\u675f\u601d\u8003\uff01\uff09",
        "</reason>",
        "",
        "## \u672a\u6765\u63a8\u6f14",
        "### \u63a8\u6f14\u8fc7\u7a0b",
        "xxx\uff08\u4e4b\u524d\u7684\u8ba1\u5212\u9047\u5230\u4e86\u54ea\u4e9b\u95ee\u9898\uff1f\u4e4b\u524d\u6709\u54ea\u4e9b\u5047\u8bbe\uff1f\u54ea\u4e9b\u662f\u9519\u7684\uff1f\uff09",
        "xxx\uff08\u5b59\u5b50\u66f0\uff1a\u591a\u7b97\u8005\u80dc\uff0c\u5c11\u7b97\u8005\u4e0d\u80dc\uff0c\u800c\u51b5\u4e8e\u65e0\u7b97\u4e4e\uff1f\u6df1\u5ea6\u601d\u8003\uff0c\u5206\u6790\u5e94\u8be5\u600e\u4e48\u505a\uff0c\u6709\u54ea\u4e9b\u9057\u6f0f\u7684\uff0c\u54ea\u4e9b\u5e94\u8be5\u505a\u3002\u56e0\u4e3a\u5f88\u591a\u4e8b\u60c5\u4e0d\u662f\u4e00\u4e0b\u5b50\u80fd\u60f3\u5230\u7684\uff0c\u6709\u4e9b\u4e8b\u60c5\u521d\u6b65\u770b\u8d77\u6765\u5f88\u91cd\u8981\uff0c\u4f46\u5176\u5b9e\u5e76\u4e0d\u3002\u6709\u4e9b\u6ca1\u8003\u8651\u5230\u7684\u98ce\u9669\uff0c\u8d8a\u60f3\u8d8a\u89c9\u5f97\u91cd\u8981\uff0c\u8fd9\u5f97\u591a\u5206\u6790\u624d\u80fd\u5f97\u5230\u7ed3\u679c\u3002\u8bf7\u4ee5\u4f60\u5468\u56f4\u7684\u5bf9\u8bdd\u8005/\u7cfb\u7edf/\u73af\u5883\u90fd\u6709\u6700\u5f3a\u65b9\u6848\u6765\u63a8\u6f14\uff0c\u8bf7\u8003\u8651\u6700\u574f\u60c5\u51b5\u4e0b\u7684\u5e94\u5bf9\u3002\u4ed6\u4eec\u4e0d\u4f1a\u72af\u4f4e\u7ea7\u9519\u8bef\uff0c\u4f60\u4e5f\u4e0d\u80fd\u3002\uff09",
        "",
        "### \u63a8\u6f14\u7ed3\u679c",
        "#### \u5f53\u52a1\u4e4b\u6025-\u5f53\u524d\u8ba1\u5212",
        "xxx\uff08\u5f53\u52a1\u4e4b\u6025\uff09",
        "#### \u672a\u6765\u7684\u8ba1\u5212",
        "xxx\uff08\u672a\u6765\u7684\u8ba1\u5212\uff09",
        "",
    ])


async def _llm(agent, prompt, max_tokens, sys=None):
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
    if sys:
        if fmt == "anthropic":
            payload["system"] = sys
        else:
            payload["messages"] = [{"role": "system", "content": sys}] + payload["messages"]
    to = aiohttp.ClientTimeout(total=300, sock_connect=30)
    async with aiohttp.ClientSession(timeout=to, trust_env=True) as sess:
        async with sess.post(url, json=payload, headers=h) as r:
            if r.status >= 400:
                raise RuntimeError("HTTP %s: %s" % (r.status, (await r.text())[:200]))
            j = await r.json()
    if fmt == "anthropic":
        out = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
        ST["last_stop"] = j.get("stop_reason")
        ST["last_usage"] = j.get("usage")
    else:
        out = j["choices"][0]["message"]["content"]
        ST["last_stop"] = (j.get("choices") or [{}])[0].get("finish_reason")
    ST["last_raw_len"] = len(out)
    return out


async def _safe(agent, prompt, mt, key, fallback, sys=None, must=None):
    """must = regex the output MUST match, else the round is rejected and the
    previous section is kept. js: if(!cl.includes('# \U0001f9e0 Self-Cognition')) return null.
    v10 only checked non-empty, so a format-drifted but non-empty reply got stored."""
    try:
        raw = await _llm(agent, prompt, mt, sys)
        ST[key + "_diag"] = {"raw": len(raw), "stop": ST.get("last_stop"),
                             "open": raw.count("<reason>"), "close": raw.count("</reason>"),
                             "head": raw[:120]}
        out = _strip(raw)
        if not out:
            raise RuntimeError("empty completion")
        if must and not re.search(must, out):
            raise RuntimeError("format check failed (missing required header)")
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
    if grew < CFG["threshold_tokens"]:
        return "grew only %d tok" % grew
    return None


async def reflect(agent, force=False):
    if ST["busy"]:
        return "busy"
    ST["busy"] = True
    try:
        cpath, npath = _paths(agent)
        ppath = npath.replace("cognition_note.md", "cognition_plan.md")
        body, sz = _tail_chars(cpath, CFG["tail_chars"])
        pc, pp = _read_prev(npath, ppath)
        tm = time.strftime("%Y-%m-%d %H:%M:%S")
        cog, plan = await asyncio.gather(
            _safe(agent, _p_cog(body, pc, tm), CFG["cog_tokens"], "err_cog", pc,
                  SYS_COG, RE_COG_HEAD),
            _safe(agent, _p_plan(body, pp, pc, tm), CFG["plan_tokens"], "err_plan", pp,
                  SYS_PLAN, None))
        if plan and plan != pp:
            try:
                with open(ppath, "w", encoding="utf-8") as f:
                    f.write(plan)
            except Exception:
                pass
        sec = _plan_section(plan)
        if plan and not sec:
            agent._log("[cognition] warn: no \u63a8\u6f14\u7ed3\u679c section in plan, head=%r"
                       % plan[:120])
        note = cog.rstrip() + (SEP + sec if sec else "")
        if len(note) > CFG["note_max_chars"]:
            note = (re.sub(r"\n[^\n]*$", "", note[:CFG["note_max_chars"] - 100])
                    + "\n\n[... truncated at hard cap %d chars ...]" % CFG["note_max_chars"])
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
        agent._log("[cognition] v%s run#%d cog=%dch plan=%dch(sec=%dch) note=%dch "
                   "consc=%dB err=%s/%s"
                   % (CFG.get("version", "?"), ST["runs"], len(cog), len(plan), len(sec),
                      len(note), sz, ST["err_cog"], ST["err_plan"]))
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
            grew = _delta_tokens(cpath, ST["last_size"] or 0, sz)
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



def sync_from_mirror(agent):
    """Handoff mirrors browser skill record (incl. cognition_note + last_reflect_at ms) to
    beings/<id>/skill/self_cognition.json. Compare with local cognition_note.md mtime; newer wins."""
    import json as _j, os as _o, time as _t
    d = agent._being_dir()
    sk = _o.path.join(d, "skill", "self_cognition.json")
    npath = _o.path.join(d, "cognition_note.md")
    try:
        v = _j.load(open(sk))
    except Exception as e:
        return "sync-skip: no mirror (%r)" % e
    bn = (v.get("cognition_note") or "").strip()
    bts = (v.get("last_reflect_at") or 0) / 1000.0
    lts = _o.path.getmtime(npath) if _o.path.exists(npath) else 0
    if bn and bts > lts:
        pn = (v.get("plan_note") or "").strip()
        note = ("synced-from-browser %s (browser reflect ts)\n\n%s\n\n## plan (browser)\n%s"
                % (_t.strftime("%F %T", _t.localtime(bts)), bn, pn))[:CFG["note_max"]]
        open(npath, "w", encoding="utf-8").write(note)
        _o.utime(npath, (bts, bts))
        return "adopted-browser (+%ds newer, %d chars)" % (int(bts - lts), len(note))
    return "kept-local (+%ds newer)" % int(lts - bts)

def install(agent):
    cpath, npath = _paths(agent)
    r = _patch(agent, npath)
    t = getattr(agent, "_cog_task", None)
    if t and not t.done():
        t.cancel()
    agent._cog_task = asyncio.get_event_loop().create_task(_watch(agent))
    agent.cognition_reflect = lambda force=True: reflect(agent, force)
    agent.cognition_state = ST
    agent.cognition_sync = lambda: sync_from_mirror(agent)
    ST["last_sync"] = sync_from_mirror(agent)
    return {"version": CFG["version"], "patch": r, "min_gap": CFG["min_gap"],
            "max_per_hour": CFG["max_per_hour"], "note_path": npath, "interval": CFG["interval"],
            "threshold_tokens": CFG["threshold_tokens"], "consciousness": os.path.getsize(cpath)}
