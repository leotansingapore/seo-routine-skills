#!/usr/bin/env python3
"""Generic internal-linking runner: one site config in, the DMA workflow out.

crawl -> Jev profile -> Jev relevance/competes -> plan (bars, caps, verbatim anchors, Jev
picks the anchor) -> apply in-text links, a Keep reading block, orphan rescue -> re-crawl.
Every stage caches on disk, so a rerun that only moves a threshold costs nothing.
Usage: site_run.py <config.json> [--check] [--stage crawl|profile|score|plan|apply|all]
"""
import json, os, re, sys, pathlib, collections, concurrent.futures as cf
from lxml import html as LH
HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))
import jev, candidates as C, anchors as A
from score_links import question

cfg = json.load(open(sys.argv[1]))
ONLY = set(json.loads(os.environ["ILM_ONLY_PAGES"])) if os.environ.get("ILM_ONLY_PAGES") else None
CHECK = "--check" in sys.argv
STAGE = sys.argv[sys.argv.index("--stage") + 1] if "--stage" in sys.argv else "all"
REPO = pathlib.Path(cfg["repo"]); WEB = pathlib.Path(cfg.get("webroot", cfg["repo"]))
OUT = pathlib.Path(cfg["out"]); OUT.mkdir(parents=True, exist_ok=True)
SITE = cfg["base_url"].rstrip("/")
HOST = re.compile(r"^https?://(www\.)?" + re.escape(re.sub(r"^https?://(www\.)?", "", SITE)))
SKIP_EXT = re.compile(r"\.(png|jpe?g|gif|svg|webp|pdf|css|js|zip|ico|mp4|webm|avif|xml|txt)(\?|$)", re.I)
ROLES = {
  "service_page": cfg.get("service_role", "Sells one of the business's own services and asks the reader to enquire, book or buy. Pricing and package pages count."),
  "guide": "Teaches a subject. How-to, explainer, checklist, definition, comparison, strategy article. Informational, not selling one specific service.",
  "roundup": "A list of tools, places, examples, statistics, ideas or trends, written to be browsed rather than to teach one method.",
  "proof": "Shows the business's own results, work or people: case study, portfolio, testimonials, reviews, results, team.",
  "utility": "A functional page with little subject matter: contact, booking, form, cart, account, thank-you, privacy policy, terms, sitemap, archive, tag or category listing.",
}

def norm(p):
    p = (p or "").strip()
    if not p.startswith("/"):
        p = "/" + p
    return p[:-1] if p != "/" and p.endswith("/") else p

def local(p):
    for cand in ("index.html" if p == "/" else p.lstrip("/") + "/index.html", p.lstrip("/") + ".html"):
        f = WEB / cand
        if f.exists():
            return f
    return None

def resolve(href, srcpath):
    if not href:
        return None
    href = href.strip()
    if href.startswith(("#", "mailto:", "tel:", "javascript:", "whatsapp:", "data:", "//")):
        return None
    if href.startswith("http"):
        if not HOST.match(href):
            return None
        href = HOST.sub("", href) or "/"
    if SKIP_EXT.search(href):
        return None
    href = href.split("#")[0].split("?")[0]
    if not href:
        return None
    if not href.startswith("/"):
        href = os.path.normpath(os.path.join(srcpath if srcpath != "/" else "", href))
    href = re.sub(r"/index\.html$", "", href); href = re.sub(r"\.html$", "", href)
    return norm(href)

def textof(el, limit=None):
    t = re.sub(r"\s+", " ", el.text_content()).strip()
    return t[:limit] if limit else t

# ---------- crawl ----------
def crawl():
    sm = (WEB / cfg["sitemap"]).read_text()
    paths = [norm(HOST.sub("", u)) for u in re.findall(r"<loc>([^<]+)</loc>", sm)]
    paths = [p for p in paths if not any(re.match(x, p) for x in cfg.get("exclude", []))]
    pages, links, missing = {}, [], []
    for p in paths:
        f = local(p)
        if not f:
            missing.append(p); continue
        doc = LH.parse(str(f)).getroot()
        title = (doc.findtext(".//title") or "").strip()
        desc = next(iter(doc.xpath('//meta[@name="description"]/@content')), "").strip()
        body = None
        for xp in cfg["body_xpath"]:
            got = doc.xpath(xp)
            if got:
                body = got[0]; break
        if body is None:
            missing.append(p + " (no body)"); continue
        for junk in body.xpath(cfg.get("strip_xpath", ".//nav | .//header | .//footer | .//script | .//style")):
            junk.getparent().remove(junk)
        rel_xp = './/*[contains(@class,"ilm-related")]' + (" | " + cfg["existing_related_xpath"] if cfg.get("existing_related_xpath") else "")
        for sec in body.xpath(rel_xp):
            for a in sec.xpath(".//a[@href]"):
                t = resolve(a.get("href"), p)
                if t and t != p:
                    links.append({"src": p, "dst": t, "anchor": textof(a, 120), "kind": "related"})
            sec.getparent().remove(sec)
        h1 = textof(body.xpath(".//h1")[0], 200) if body.xpath(".//h1") else (textof(doc.xpath("//h1")[0], 200) if doc.xpath("//h1") else "")
        h2s = [textof(h, 160) for h in body.xpath(".//h2")][:14]
        btext = textof(body)
        for a in body.xpath(".//a[@href]"):
            t = resolve(a.get("href"), p)
            if t and t != p:
                links.append({"src": p, "dst": t, "anchor": textof(a, 120), "kind": "text"})
        pages[p] = {"path": p, "title": title, "desc": desc, "h1": h1, "h2s": h2s, "words": len(btext.split()),
                    "tpl": "article" if (cfg.get("edit_marker") and cfg["edit_marker"] in f.read_text()
                                         and p not in cfg.get("never_edit", [])) else "page",
                    "canonical": "", "sample": btext[:1400], "file": str(f.relative_to(REPO)) if f.is_relative_to(REPO) else str(f)}
    json.dump(pages, open(OUT / "pages.json", "w")); json.dump(links, open(OUT / "links.json", "w"))
    print(f"[crawl] pages {len(pages)} links {len(links)} missing {len(missing)} editable {sum(1 for v in pages.values() if v['tpl']=='article')}")
    for m in missing[:5]:
        print("   miss", m)

# ---------- profile ----------
def profile():
    P = json.load(open(OUT / "pages.json"))
    have = json.load(open(OUT / "profiles.json")) if (OUT / "profiles.json").exists() else {}
    have = {k: v for k, v in have.items() if k in P}
    Q = {"cluster": {"type": "choice", "instructions": "Which single subject area of `business` does this `page` belong to? Judge it by what the page is actually about.", "criteria": cfg["clusters"]},
         "page_role": {"type": "choice", "instructions": "What job does this `page` do for a visitor?", "criteria": ROLES}}
    def one(p):
        pg = P[p]
        st = {"business": cfg["business"], "page": {"url": p, "title": pg["title"], "heading": pg["h1"], "meta_description": pg["desc"],
              "section_headings": pg["h2s"], "word_count": pg["words"], "opening_text": pg["sample"][:1100]}}
        return p, jev.ask(st, Q, label=f"profile {p}")
    res = dict(have)
    with cf.ThreadPoolExecutor(5) as ex:
        for p, a in ex.map(one, [p for p in P if p not in have]):
            if a:
                res[p] = {"cluster": a["cluster"]["choice"], "cluster_conf": round(a["cluster"]["confidence"], 3),
                          "role": a["page_role"]["choice"], "role_conf": round(a["page_role"]["confidence"], 3)}
    json.dump(res, open(OUT / "profiles.json", "w"))
    print("[profile]", len(res), dict(collections.Counter(v["cluster"] for v in res.values())), dict(collections.Counter(v["role"] for v in res.values())), jev.report())

def sstate(pg, prof):
    return {"site": cfg["business"], "source_page": {"url": pg["path"], "title": pg["title"], "heading": pg["h1"], "meta_description": pg["desc"],
            "section_headings": pg["h2s"], "what_it_is": f"{prof['role']} about {prof['cluster']}", "text": pg["sample"][:1200]}}

# ---------- score ----------
def score():
    P = json.load(open(OUT / "pages.json")); F = json.load(open(OUT / "profiles.json")); L = json.load(open(OUT / "links.json"))
    existing = collections.defaultdict(set)
    for l in L:
        existing[l["src"]].add(l["dst"])
    vec = C.build(P, F)
    n_svc = cfg.get("n_service", 8); n_peer = cfg.get("n_peer", 16)
    def one(s):
        cands = C.shortlist(s, P, F, vec, existing, n_service=n_svc, n_peer=n_peer, n_proof=2)
        if not cands:
            return s, []
        qs = {}
        for i, c in enumerate(cands):
            r, cm = question(P[c["path"]], F[c["path"]]); qs[f"r{i}"], qs[f"c{i}"] = r, cm
        a = jev.ask(sstate(P[s], F[s]), qs, label=f"links {s}")
        if not a:
            return s, None
        out = [{**c, "jev": round(a[f"r{i}"]["noul"], 3), "competes": round(a[f"c{i}"]["noul"], 3)} for i, c in enumerate(cands) if a.get(f"r{i}") and a.get(f"c{i}")]
        out.sort(key=lambda x: -x["jev"]); return s, out
    res = json.load(open(OUT / "link_scores.json")) if (OUT / "link_scores.json").exists() else {}
    res = {k: [c for c in v if c["path"] in P] for k, v in res.items() if k in P}
    todo = [p for p in P if p in F and (ONLY is None or p in ONLY) and (ONLY is not None or p not in res)] if ONLY is not None or res else [p for p in P if p in F]
    with cf.ThreadPoolExecutor(5) as ex:
        for s, r in ex.map(one, todo):
            if r is not None:
                res[s] = r
    json.dump(res, open(OUT / "link_scores.json", "w"))
    pairs = sum(len(v) for v in res.values())
    print(f"[score] {len(res)} sources, {pairs} pairs; {jev.report()}")

# ---------- container helpers ----------
def container_span(raw):
    """(start, end) of the editable article html: from the edit marker's tag to its matching close."""
    mk = cfg["edit_marker"]; i = raw.find(mk)
    if i < 0:
        return None
    if not mk.startswith("<"):          # an attribute marker: walk back to its tag
        i = raw.rfind("<", 0, i)
    tag = re.match(r"<([a-zA-Z0-9]+)", raw[i:]).group(1)
    depth, pos = 0, i
    pat = re.compile(r"</?" + tag + r"\b", re.I)
    for m in pat.finditer(raw, i):
        if raw[m.start():m.start() + 2] == "</":
            depth -= 1
            if depth == 0:
                return (i, m.start())
        else:
            depth += 1
    return None
A.article_span = container_span     # anchors module reads the container through this

# ---------- plan ----------
NONE = "none of these"
def plan():
    P = json.load(open(OUT / "pages.json")); F = json.load(open(OUT / "profiles.json")); S = json.load(open(OUT / "link_scores.json")); L = json.load(open(OUT / "links.json"))
    REL, DUP, MAXN, MAXIN = cfg.get("rel_bar", 0.75), cfg.get("dup_bar", 0.45), cfg.get("max_new", 4), cfg.get("max_new_inbound", 25)
    inbound = collections.Counter(l["dst"] for l in L if l["kind"] == "text" and l["dst"] in P); new_in = collections.Counter()
    bodies = {}
    def body_of(p):
        if p not in bodies:
            raw = (REPO / P[p]["file"]).read_text(); sp = container_span(raw)
            b = raw[sp[0]:sp[1]] if sp else None
            if b is not None:
                m = RELATED_RE.search(b)          # never anchor inside our own block; it sits at the end
                if m:
                    b = b[:m.start()]
            bodies[p] = b
        return bodies[p]
    picks = []
    for s, cands in S.items():
        if P[s]["tpl"] != "article" or body_of(s) is None or (ONLY is not None and s not in ONLY):
            continue
        ok = [c for c in cands if c["jev"] >= REL and c["competes"] < DUP and c["path"] != "/"]
        ok.sort(key=lambda c: (-round(c["jev"], 1), inbound[c["path"]] + new_in[c["path"]]))
        taken = 0
        for c in ok:
            if taken >= MAXN:
                break
            if new_in[c["path"]] >= MAXIN:
                continue
            spans = A.find_spans(body_of(s), P[c["path"]], c["path"])
            if not spans:
                continue
            picks.append({"src": s, "dst": c["path"], "jev": c["jev"], "competes": c["competes"], "spans": spans}); new_in[c["path"]] += 1; taken += 1
    by = collections.defaultdict(list)
    for p in picks:
        by[p["src"]].append(p)
    def aq(tgt_pg, tgt_path, spans):
        crit = {s["phrase"]: {"appears_in": s["context"]} for s in spans}
        crit[NONE] = "No phrase above is about the subject of `link_target`. Linking any of them would send the reader somewhere the phrase did not promise."
        return {"type": "choice", "instructions": {"link_target": {"url": tgt_path, "title": tgt_pg["title"], "heading": tgt_pg["h1"], "meta_description": tgt_pg["desc"]},
                "question": "Each option is a phrase taken word for word out of `source_page`. Which one should be turned into the link to `link_target`? Pick the phrase whose own wording tells the reader what they will get by clicking."}, "criteria": crit}
    def one(s):
        items = by[s]
        qs = {f"a{i}": aq(P[it["dst"]], it["dst"], it["spans"]) for i, it in enumerate(items)}
        a = jev.ask(sstate(P[s], F[s]), qs, label=f"anchor {s}")
        out = []
        for i, it in enumerate(items):
            ans = (a or {}).get(f"a{i}")
            if not ans or ans["choice"] == NONE:
                continue
            span = next((x for x in it["spans"] if x["phrase"] == ans["choice"]), None)
            if span:
                out.append({**{k: v for k, v in it.items() if k != "spans"}, "spans": [x for x in it["spans"] if x["phrase"] != span["phrase"]], "anchor": span["phrase"], "span": span})
        return out
    plan_rows = []
    with cf.ThreadPoolExecutor(5) as ex:
        for rows in ex.map(one, list(by)):
            plan_rows.extend(rows)
    json.dump(plan_rows, open(OUT / "link_plan.json", "w"))
    print(f"[plan] {len(picks)} pairs with a span -> {len(plan_rows)} anchored links on {len(set(r['src'] for r in plan_rows))} pages; {jev.report()}")

# ---------- apply ----------
def esc(s): return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
def clean_title(t):
    for b in cfg.get("brand_suffixes", []):
        t = re.sub(r"\s*[-|:]\s*" + re.escape(b) + r".*$", "", t, flags=re.I)
    return t.strip()
RELATED_RE = re.compile(r'<section class="ilm-related".*?</section>', re.S)
def related_html(items):
    lis = "".join(f'<li><a href="{p}">{esc(t)}</a></li>' for p, t in items)
    return ('<section class="ilm-related" style="margin:2.5rem 0 1rem;padding-top:1.25rem;border-top:1px solid rgba(0,0,0,.12)">'
            f'<h3 style="margin:0 0 .6rem;font-size:1.05rem;line-height:1.3">{esc(cfg.get("related_heading","Keep reading"))}</h3>'
            f'<ul style="margin:0;padding-left:1.2rem;line-height:1.75">{lis}</ul></section>')

def apply():
    P = json.load(open(OUT / "pages.json")); F = json.load(open(OUT / "profiles.json")); S = json.load(open(OUT / "link_scores.json")); L = json.load(open(OUT / "links.json"))
    plan_rows = json.load(open(OUT / "link_plan.json"))
    stats = collections.Counter()
    # 1. in-text links
    by = collections.defaultdict(list)
    for r in plan_rows:
        by[r["src"]].append(r)
    for src, rows in by.items():
        f = REPO / P[src]["file"]; raw = f.read_text(); sp = container_span(raw)
        if not sp:
            continue
        i, j = sp; scope = raw[i:j]
        edits = []
        for r in rows:
            if f'href="{r["dst"]}"' in scope or f'href="{SITE}{r["dst"]}"' in scope:
                stats["already linked"] += 1; continue
            opts = [(i + o["start"], i + o["end"], o["phrase"]) for o in [r["span"]] + r["spans"] if raw[i + o["start"]:i + o["end"]] == o["phrase"]]
            if opts:
                edits.append((r["dst"], opts))
        kept, claimed = [], []
        for dst, opts in edits:
            got = next(((a, b, p) for a, b, p in opts if all(b <= x or a >= y for x, y in claimed)), None)
            if not got:
                stats["span taken"] += 1; continue
            claimed.append((got[0], got[1])); kept.append((got[0], got[1], dst, got[2]))
        for a, b, dst, phrase in sorted(kept, key=lambda k: -k[0]):
            raw = raw[:a] + '<a href="' + dst + '">' + phrase + "</a>" + raw[b:]
        if kept:
            stats["in-text links"] += len(kept); stats["pages with in-text links"] += 1
            if not CHECK:
                f.write_text(raw)
    # 2. Keep reading block on every editable page (replace if present), 3 best peers.
    # A site whose template already carries its own module (DMA's dma-related) opts out.
    RELB, DUPB = cfg.get("related_rel_bar", 0.55), cfg.get("related_dup_bar", 0.60)
    for p, pg in P.items():
        if cfg.get("no_related_block") or pg["tpl"] != "article" or (ONLY is not None and p not in ONLY):
            continue
        f = REPO / pg["file"]; raw = f.read_text(); sp = container_span(raw)
        if not sp:
            continue
        i, j = sp; art = raw[i:j]
        cands = [c for c in S.get(p, []) if c["jev"] >= RELB and c["competes"] < DUPB and c["path"] in P and c["path"] != p
                 and F.get(c["path"], {}).get("role") in ("guide", "roundup", "proof") and f'href="{c["path"]}"' not in art]
        cands.sort(key=lambda c: -c["jev"]); top = cands[:3]
        if not top:
            continue
        html = related_html([(c["path"], clean_title(P[c["path"]]["title"])) for c in top])
        if RELATED_RE.search(art):
            new = raw[:i] + RELATED_RE.sub(html, art, count=1) + raw[j:]
        else:
            new = raw[:j] + html + raw[j:]
        if new != raw:
            stats["keep-reading blocks"] += 1
            if not CHECK:
                f.write_text(new)
    print("[apply]", dict(stats))

def rescue():
    """Orphans: the question runs the other way round, orphan as state, donors as questions."""
    P = json.load(open(OUT / "pages.json")); F = json.load(open(OUT / "profiles.json")); L = json.load(open(OUT / "links.json"))
    inb = collections.Counter(l["dst"] for l in L if l["dst"] in P)
    already = collections.defaultdict(set)
    for l in L:
        already[l["src"]].add(l["dst"])
    orphans = [p for p in P if inb[p] == 0 and p in F and F[p]["role"] != "utility"]
    donors = [p for p in P if P[p]["tpl"] == "article" and p in F]
    if cfg.get("no_related_block"):
        print("[rescue] skipped: this site owns its related module"); return
    if not orphans or not donors:
        print("[rescue] nothing to do"); return
    vec = C.build(P, F)
    def q(d):
        return {"type": "noul", "instructions": {"donor_page": {"url": d, "title": P[d]["title"], "heading": P[d]["h1"], "meta_description": P[d]["desc"], "section_headings": P[d]["h2s"][:8], "what_it_is": f"{F[d]['role']} about {F[d]['cluster']}"},
                "question": "`orphan_page` currently has no link pointing to it from anywhere in the site's content. Should `donor_page` be the page that points to it, in a short 'Keep reading' list at the end of `donor_page`?"},
                "criteria": {"true": "Someone who has just finished reading `donor_page` would want `orphan_page` next: it continues the same subject, answers the question `donor_page` leaves open, or is the service page for what `donor_page` describes.",
                             "false": "`donor_page` is about a different subject, so the link would look out of place at the end of it, or the two are the same article and one should be merged into the other rather than linked."}}
    def one(o):
        cands = sorted((d for d in donors if d != o and o not in already[d]), key=lambda d: -C.cosine(vec[o], vec[d]))[:12]
        qs = {f"d{i}": q(d) for i, d in enumerate(cands)}
        st = {"orphan_page": {"url": o, "title": P[o]["title"], "heading": P[o]["h1"], "meta_description": P[o]["desc"], "section_headings": P[o]["h2s"], "what_it_is": f"{F[o]['role']} about {F[o]['cluster']}", "text": P[o]["sample"][:1100]}}
        a = jev.ask(st, qs, label=f"orphan {o}")
        return o, sorted(((round(a[f"d{i}"]["noul"], 3), d) for i, d in enumerate(cands) if a and a.get(f"d{i}")), reverse=True)
    used = collections.Counter(); picks = []
    with cf.ThreadPoolExecutor(5) as ex:
        res = dict(ex.map(one, orphans))
    for o, sc in sorted(res.items(), key=lambda kv: -(kv[1][0][0] if kv[1] else 0)):
        for jv, d in sc:
            if jv < cfg.get("orphan_bar", 0.55):
                break
            if used[d] >= 2:
                continue
            picks.append((o, d, jv)); used[d] += 1; break
    by = collections.defaultdict(list)
    for o, d, _ in picks:
        by[d].append(o)
    done = 0
    for d, os_ in by.items():
        f = REPO / P[d]["file"]; raw = f.read_text(); sp = container_span(raw)
        if not sp:
            continue
        i, j = sp; art = raw[i:j]; m = RELATED_RE.search(art)
        items = [(o, clean_title(P[o]["title"])) for o in os_ if f'href="{o}"' not in art]
        if not items:
            continue
        if m:
            lis = "".join(f'<li><a href="{p}">{esc(t)}</a></li>' for p, t in items)
            block = m.group(0).replace("</ul>", lis + "</ul>", 1)
            new = raw[:i] + art[:m.start()] + block + art[m.end():] + raw[j:]
        else:
            new = raw[:j] + related_html(items) + raw[j:]
        done += len(items)
        if not CHECK:
            f.write_text(new)
    print(f"[rescue] orphans {len(orphans)}, rescued {len(picks)}, links written {done}; {jev.report()}")

def report():
    global OUT
    P = json.load(open(OUT / "pages.json")); Lb = json.load(open(OUT / "links.json"))
    out2 = OUT / "after"; out2.mkdir(exist_ok=True)
    o = OUT; OUT = out2; crawl(); OUT = o
    La = json.load(open(out2 / "links.json"))
    def s(L, kinds):
        ls = [l for l in L if l["kind"] in kinds and l["dst"] in P]; i = collections.Counter(l["dst"] for l in ls)
        return len(ls), sum(1 for p in P if i[p] == 0), sum(1 for p in P if i[p] <= 1)
    for lab, k in (("in-text", {"text"}), ("all in-page", {"text", "related"})):
        b = s(Lb, k); a = s(La, k)
        print(f"[report] {lab:12s} links {b[0]:6d} -> {a[0]:6d} | zero-inbound {b[1]:4d} -> {a[1]:4d} | <=1 inbound {b[2]:4d} -> {a[2]:4d}")

if __name__ == "__main__":
    stages = ["crawl", "profile", "score", "plan", "apply", "rescue", "report"] if STAGE == "all" else [STAGE]
    for st in stages:
        if st == "profile" and (OUT / "profiles.json").exists() and STAGE == "all":
            print("[profile] cached"); continue
        if st == "score" and (OUT / "link_scores.json").exists() and STAGE == "all":
            print("[score] cached"); continue
        globals()[st]()
