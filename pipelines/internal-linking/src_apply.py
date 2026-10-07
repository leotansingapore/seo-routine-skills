#!/usr/bin/env python3
"""In-text links written into a site's SOURCE (not rendered HTML) for sites whose post bodies
live in a repo file: Markdown strings in a TS module (examprep) or HTML strings in a JSON file
(internshipsite). Same decisions as everywhere else: relevance >= 0.75, not competing, a phrase
already in the body taken from the target's own title, Jev picks the phrase or declines, and
the promise question drops a generic phrase aimed at a specific page.
Usage: src_apply.py <config.json> <adapter> [--check]"""
import json, re, sys, pathlib, collections, concurrent.futures as cf
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import jev, anchors as A, promise
cfg = json.load(open(sys.argv[1])); ADAPTER = sys.argv[2]; CHECK = "--check" in sys.argv
O = pathlib.Path(cfg["out"]); REPO = pathlib.Path(cfg["repo"])
P = json.load(open(O / "pages.json")); F = json.load(open(O / "profiles.json")); S = json.load(open(O / "link_scores.json"))
REL, DUP, MAXN, MAXIN, PROMISE = cfg.get("rel_bar", 0.75), cfg.get("dup_bar", 0.45), cfg.get("max_new", 3), cfg.get("max_new_inbound", 20), 0.60

# ---------- adapters: {url: body}, format, and a writer ----------
if ADAPTER == "examprep":
    SRC = REPO / "src/content/blog/articles.generated.ts"; TEXT = SRC.read_text(); FMT = "md"
    ENC = re.compile(r'"slug":\s*"([^"]+)"')
    bodies = {}
    for m in re.finditer(r'\{\s*"slug":\s*"([^"]+)".*?"body":\s*("(?:[^"\\]|\\.)*")', TEXT, re.S):
        bodies["/blog/" + m.group(1)] = json.loads(m.group(2))
    def write(new_bodies):
        t = TEXT
        for url, (old, new) in new_bodies.items():
            eo, en = json.dumps(old, ensure_ascii=False), json.dumps(new, ensure_ascii=False)
            if t.count(eo) != 1: print("  skip (not unique)", url); continue
            t = t.replace(eo, en)
        SRC.write_text(t)
elif ADAPTER == "internshipsite":
    SRC = REPO / "src/content/blog/posts.json"; DATA = json.loads(SRC.read_text()); FMT = "html"
    bodies = {"/blog/" + p["slug"]: p["content"] for p in DATA}
    def write(new_bodies):
        for p in DATA:
            u = "/blog/" + p["slug"]
            if u in new_bodies: p["content"] = new_bodies[u][1]
        SRC.write_text(json.dumps(DATA, indent=2, ensure_ascii=False) + "\n")
elif ADAPTER.startswith("json:"):
    # json:<bodies.json>:<html|md>:<out.json> - bodies keyed by url, as read from a database;
    # the new bodies are written to out.json for db_write.py, never straight to the database.
    _, BIN, FMT, BOUT = ADAPTER.split(":")
    bodies = json.load(open(BIN)); SRC = pathlib.Path(BIN)
    def write(new_bodies):
        json.dump({u: {"old": o, "new": n} for u, (o, n) in new_bodies.items()}, open(BOUT, "w"))
else:
    raise SystemExit("unknown adapter")
print(f"[src] {len(bodies)} bodies from {SRC.name} ({FMT})")

# ---------- linkable stretches ----------
MDLINK = re.compile(r"!?\[[^\]]*\]\([^)]*\)|`[^`]*`|https?://\S+|<[^>]+>")
def md_nodes(body):
    """(start, end, text) for prose lines: not headings, tables, quotes, code, lists of links."""
    out, pos, fence = [], 0, False
    for line in body.split("\n"):
        s = pos; pos += len(line) + 1
        st = line.strip()
        if st.startswith("```"): fence = not fence; continue
        if fence or not st or st[0] in "#|>" or st.startswith("!["): continue
        if len(st.split()) < 6: continue
        # cut the line at existing links/code so a phrase never lands inside one
        last = 0
        for m in MDLINK.finditer(line):
            if m.start() > last: out.append((s + last, s + m.start(), line[last:m.start()]))
            last = m.end()
        if last < len(line): out.append((s + last, s + len(line), line[last:]))
    return out
def nodes(body):
    return md_nodes(body) if FMT == "md" else [(a, b, t) for a, b, t in A.linkable_text(body)]
def linked_targets(body):
    hrefs = re.findall(r"\]\((/[^)\s#?]*)", body) if FMT == "md" else re.findall(r'href="(?:https?://[^/"]+)?(/[^"#?]*)"', body)
    return {h.rstrip("/") or "/" for h in hrefs}
WORDRX = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\-]*")
def extend(text, a, b, titles):
    """Grow [a,b) a word at a time, either side, while the span still reads as a run of the
    target's own title: 'should we hire' becomes 'why should we hire you'."""
    norm = lambda x: re.sub(r"\s+", " ", x.lower()).strip()
    grew = True
    while grew:
        grew = False
        m = re.match(r"(\s+)([A-Za-z0-9][A-Za-z0-9'\-]*)", text[b:])
        if m and any(norm(text[a:b + m.end()]) in t for t in titles):
            b += m.end(); grew = True
        m = re.search(r"([A-Za-z0-9][A-Za-z0-9'\-]*)(\s+)$", text[:a])
        if m and any(norm(text[m.start():b]) in t for t in titles):
            a = m.start(); grew = True
    return a, b
def truncated(span, after, titles):
    """True when every title holding the span carries on with a content word the text does not
    ('resume with no work' + title 'experience' vs text 'history'): the anchor is a cut compound."""
    nxt = re.match(r"\s+([A-Za-z0-9][A-Za-z0-9'\-]*)", after)
    nxt = nxt.group(1).lower() if nxt else ""
    sp = re.sub(r"\s+", " ", span.lower()); hits = 0; cut = 0
    for t in titles:
        i = t.find(sp)
        if i < 0: continue
        hits += 1
        follow = re.match(r"\s*[^A-Za-z0-9]*\s*([A-Za-z0-9][A-Za-z0-9'\-]*)", t[i + len(sp):])
        w = follow.group(1).lower() if follow and t[i + len(sp):i + len(sp) + 1] == " " else ""
        if w and w not in A.EDGE_STOP and w not in A.GENERIC and w != nxt: cut += 1
    return hits > 0 and cut == hits
# words in 15%+ of this site's titles name nothing here ("virtual assistant" on a VA agency)
_TW = collections.Counter(w for p in P.values() for w in set(re.findall(r"[a-z0-9]+", (p["title"] + " " + p["h1"]).lower())))
SITE_GENERIC = {w for w, n in _TW.items() if n >= 0.15 * len(P)}
def distinctive(phrase):
    ws = [w for w in re.findall(r"[a-z0-9]+", phrase.lower()) if w not in A.EDGE_STOP and w not in A.GENERIC and len(w) > 2]
    return any(w not in SITE_GENERIC for w in ws)
def spans(body, tgt):
    phrases = [p for p in A.target_phrases(P[tgt], tgt) if distinctive(p)]; found, seen = [], set()
    titles = [re.sub(r"\s+", " ", x.lower()) for x in (P[tgt]["title"], P[tgt]["h1"], tgt.rsplit("/", 1)[-1].replace("-", " ")) if x]
    for ph in phrases:
        pat = re.compile(r"(?<![A-Za-z0-9'\-])" + re.escape(ph).replace(r"\ ", r"\s+") + r"(?![A-Za-z0-9'\-])", re.I)
        best = None
        for s, e, text in nodes(body):
            for m in pat.finditer(text):
                a0, b0 = extend(text, m.start(), m.end(), titles)
                am = re.match(r"(?i)(a|an|the)\s+", text[a0:b0])
                if am and b0 - a0 - am.end() > 0: a0 += am.end()   # never start a link on an article
                got = text[a0:b0]
                if "&" in got or "*" in got: continue
                if truncated(got, text[b0:], titles): continue
                if best is None or len(got) > len(best[0]):      # the fullest run of the title wins
                    best = (got, s + a0, s + b0, text[max(0, a0 - 130):b0 + 130])
        if best and best[0].lower() not in seen:
            seen.add(best[0].lower())
            found.append({"phrase": best[0], "start": best[1], "end": best[2], "words": len(best[0].split()), "context": best[3]})
    found.sort(key=lambda x: -x["words"]); kept = []
    for c in found:
        if any(c["phrase"].lower() != k["phrase"].lower() and c["phrase"].lower() in k["phrase"].lower() for k in kept): continue
        kept.append(c)
    return kept[:5]

# ---------- plan ----------
new_in = collections.Counter(); todo = []
for src, cands in S.items():
    if src not in bodies: continue
    body = bodies[src]; have = linked_targets(body)
    ok = sorted([c for c in cands if c["jev"] >= REL and c["competes"] < DUP and c["path"] not in have and c["path"] != "/"
                 and c["path"] != src], key=lambda c: -c["jev"])
    items = []
    for c in ok:
        if len(items) >= MAXN: break
        if new_in[c["path"]] >= MAXIN: continue
        sp = spans(body, c["path"])
        if sp: items.append({"dst": c["path"], "spans": sp}); new_in[c["path"]] += 1
    if items: todo.append((src, items))
print(f"[plan] pairs with a verbatim span: {sum(len(i) for _, i in todo)} on {len(todo)} posts")
NONE = "none of these"
def sstate(p):
    pg, pr = P[p], F[p]
    return {"site": cfg["business"], "source_page": {"url": p, "title": pg["title"], "heading": pg["h1"], "meta_description": pg["desc"],
            "section_headings": pg["h2s"], "what_it_is": f"{pr['role']} about {pr['cluster']}", "text": pg["sample"][:1200]}}
def ask(job):
    src, items = job; qs = {}
    for i, it in enumerate(items):
        crit = {sp["phrase"]: {"appears_in": sp["context"]} for sp in it["spans"]}
        crit[NONE] = "No phrase above is about the subject of `link_target`. Linking any of them would send the reader somewhere the phrase did not promise."
        t = P[it["dst"]]
        qs[f"a{i}"] = {"type": "choice", "instructions": {"link_target": {"url": it["dst"], "title": t["title"], "heading": t["h1"], "meta_description": t["desc"]},
            "question": "Each option is a phrase taken word for word out of `source_page`. Which one should be turned into the link to `link_target`? Pick the phrase whose own wording tells the reader what they will get by clicking."}, "criteria": crit}
    a = jev.ask(sstate(src), qs, label=f"anchor {src}"); out = []
    for i, it in enumerate(items):
        ans = (a or {}).get(f"a{i}")
        if ans and ans["choice"] != NONE:
            sp = next((x for x in it["spans"] if x["phrase"] == ans["choice"]), None)
            if sp: out.append((it["dst"], sp))
    if out:
        pr = promise.check(sstate(src), [(d, sp["phrase"], sp["context"]) for d, sp in out], P, label=f"promise {src}")
        out = [(d, sp, x) for (d, sp), x in zip(out, pr)]
    return src, out
picked, dropped, new_bodies, samples = 0, 0, {}, []
with cf.ThreadPoolExecutor(5) as ex:
    for src, out in ex.map(ask, todo):
        body = bodies[src]; claimed = []; new = body
        for dst, sp, x in sorted(out, key=lambda o: -o[1]["start"]):
            if x is None or x < PROMISE: dropped += 1; continue
            a, b = sp["start"], sp["end"]
            if any(not (b <= y or a >= z) for y, z in claimed) or body[a:b] != sp["phrase"]: continue
            claimed.append((a, b))
            link = f"[{sp['phrase']}]({dst})" if FMT == "md" else f'<a href="{dst}">{sp["phrase"]}</a>'
            new = new[:a] + link + new[b:]; picked += 1
            if len(samples) < 10: samples.append((src, dst, sp["phrase"], x))
        if new != body: new_bodies[src] = (body, new)
print(f"[apply] {'would add' if CHECK else 'added'} {picked} links on {len(new_bodies)} posts; promise gate dropped {dropped}; {jev.report()}")
for s, d, p, x in samples: print(f"   [{p}] -> {d}   (promise {x:.2f})")
if not CHECK and new_bodies: write(new_bodies)
