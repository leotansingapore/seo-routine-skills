#!/usr/bin/env python3
"""Weekly internal-linking refresh across the fleet.

For each site: refresh the source (a live mirror, or a fresh worktree of the repo), crawl,
find pages that were not there last week, profile and score only those, then either
regenerate the site's related-picks map (map sites) or write in-text links and a Keep
reading block into the new posts (static sites). Each new page is also offered to two
donors so it has an inbound link from day one. Commits from a throwaway worktree, pushes
main, and never touches a main checkout. A site with nothing new is skipped.

Usage: weekly.py [site ...] [--check] [--full]
  --check  do everything except commit and push
  --full   treat every page as new (rebuild maps from scratch)
"""
import json, os, re, sys, shutil, subprocess, time, pathlib, collections
HOME = pathlib.Path.home()
D = HOME / ".local/share/internal-linking"; PIPE = D / "pipeline"
PY = str(HOME / ".local/share/uv/tools/scrapling/bin/python")
sys.path.insert(0, str(PIPE))
os.environ.setdefault("JEV_CACHE", str(D / "jevcache"))
import jev, candidates as C
CHECK = "--check" in sys.argv; FULL = "--full" in sys.argv
NAMES = [a for a in sys.argv[1:] if not a.startswith("--")] or sorted(p.stem for p in (D / "sites").glob("*.json"))
LOG = D / "logs" / f"{time.strftime('%Y-%m-%d')}.log"

# how each site consumes its picks
MAP = {
  "catalyst":        {"file": "src/data/internalLinks.json", "fmt": "catalyst", "cap": 6},
  "vepco":         {"file": "src/data/relatedGuides.json", "fmt": "related", "cap": 4},
  "examprep":           {"file": "src/content/blog/related.json", "fmt": "related", "cap": 3},
  "internshipsite":     {"file": "src/content/blog/related.json", "fmt": "related", "cap": 3},
  "searchblueprint": {"file": "src/app/blog/related.json", "fmt": "related", "cap": 3},
  "financeblog":       {"file": "src/data/relatedArticles.json", "fmt": "related", "cap": 6},
  "cleaningco":          {"file": "api/_related.json", "fmt": "related", "cap": 3},
}
STATIC = {"dma", "immigration", "paintingco", "parentingblog", "cleaningco"}   # cleaningco: static posts too
EXTRA_SITEMAP = {"cleaningco": ["https://www.cleaningco.example/blog-sitemap.xml"]}
POST_PREFIX = {"parentingblog": "/blogs/", "cleaningco": "/blog/"}

def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"; print(line, flush=True)
    with open(LOG, "a") as fh: fh.write(line + "\n")

def sh(cmd, cwd=None, check=True, env=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env={**os.environ, **(env or {})})
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(cmd)} -> {r.returncode}\n{r.stdout[-800:]}\n{r.stderr[-800:]}")
    return r

def fresh_worktree(repo, name):
    wt = HOME / "worktrees.noindex" / f"il-{name}"
    if wt.exists():
        sh(["git", "-C", repo, "worktree", "remove", "--force", str(wt)], check=False); shutil.rmtree(wt, ignore_errors=True)
    sh(["git", "-C", repo, "fetch", "-q", "origin"])
    sh(["git", "-C", repo, "worktree", "add", "--detach", str(wt), "origin/main"])
    return wt

def mirror(cfg, name):
    out = D / "mirror" / name; shutil.rmtree(out, ignore_errors=True)
    sh([PY, str(PIPE / "mirror.py"), cfg["base_url"], str(out)])
    for extra in EXTRA_SITEMAP.get(name, []):                       # posts served from a second sitemap
        import urllib.request
        sm = urllib.request.urlopen(urllib.request.Request(extra, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read().decode()
        urls = re.findall(r"<loc>([^<]+)</loc>", sm)
        main = (out / "sitemap.xml").read_text()
        (out / "sitemap.xml").write_text(main.replace("</urlset>", "".join(f"<url><loc>{u}</loc></url>" for u in urls if u not in main) + "</urlset>"))
        for u in urls:
            p = re.sub(r"^https?://[^/]+", "", u).rstrip("/"); f = out / (p.lstrip("/") + "/index.html")
            if not f.exists():
                try:
                    html = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read().decode("utf-8", "replace")
                    f.parent.mkdir(parents=True, exist_ok=True); f.write_text(html)
                except Exception as e: log(f"  mirror miss {p}: {e}")

def run_stage(cfg_path, stage, only=None):
    env = {"ILM_ONLY_PAGES": json.dumps(sorted(only))} if only is not None else {}
    r = sh([PY, str(PIPE / "site_run.py"), str(cfg_path), "--stage", stage], env=env)
    for line in r.stdout.splitlines():
        if line.startswith("["): log("  " + line[:220])

def donors_for(new_pages, P, F, cfg, pool):
    """Two donors per new page, asked the way the orphan rescue asks."""
    vec = C.build(P, F); out = {}
    for o in new_pages:
        if o not in F: continue
        cands = sorted((d for d in pool if d != o and d in F), key=lambda d: -C.cosine(vec[o], vec[d]))[:12]
        if not cands: continue
        qs = {}
        for i, d in enumerate(cands):
            qs[f"d{i}"] = {"type": "noul", "instructions": {"donor_page": {"url": d, "title": P[d]["title"], "heading": P[d]["h1"], "meta_description": P[d]["desc"], "what_it_is": f"{F[d]['role']} about {F[d]['cluster']}"},
                "question": "`orphan_page` is new and nothing links to it yet. Should `donor_page` be a page that points to it, in a short related-posts list at the end of `donor_page`?"},
                "criteria": {"true": "Someone who has just finished reading `donor_page` would want `orphan_page` next: it continues the same subject or answers the question `donor_page` leaves open.",
                             "false": "`donor_page` is about a different subject, or the two are the same article and one should be merged into the other rather than linked."}}
        st = {"orphan_page": {"url": o, "title": P[o]["title"], "heading": P[o]["h1"], "meta_description": P[o]["desc"], "section_headings": P[o]["h2s"], "text": P[o]["sample"][:1100]}}
        a = jev.ask(st, qs, label=f"donor {o}")
        if not a: continue
        sc = sorted(((a[f"d{i}"]["noul"], d) for i, d in enumerate(cands) if a.get(f"d{i}")), reverse=True)
        out[o] = [d for x, d in sc if x >= cfg.get("orphan_bar", 0.55)][:2]
    return out

def slug_of(name, path):
    return path.replace(POST_PREFIX.get(name, "/blog/"), "", 1)

def rebuild_map(name, cfg, wt, new_pages):
    """Recompute picks for new pages, add each new page to its donors, keep everything else."""
    O = pathlib.Path(cfg["out"]); P = json.load(open(O / "pages.json")); F = json.load(open(O / "profiles.json")); S = json.load(open(O / "link_scores.json"))
    spec = MAP[name]; path = wt / spec["file"]; doc = json.load(open(path)) if path.exists() else {}
    pre = POST_PREFIX.get(name, "/blog/"); cap = spec["cap"]
    posts = [p for p in P if p.startswith(pre) and not p.startswith(pre + "tag/") and not p.startswith(pre + "page/") and not p.startswith(pre + "category/")]
    REL, DUP = cfg.get("related_rel_bar", 0.55), cfg.get("related_dup_bar", 0.60)
    def picks(src, pred):
        return [c["path"] for c in sorted(S.get(src, []), key=lambda c: -c["jev"]) if pred(c["path"]) and c["jev"] >= REL and c["competes"] < 0.45 and c["path"] != src]
    isart = lambda p: p in posts
    changed = 0
    if spec["fmt"] == "catalyst":
        links = doc.setdefault("links", {})
        for n in new_pages:
            if n not in posts: continue
            e = {}
            a = [{"url": p, "score": s} for p, s in ((c["path"], c["jev"]) for c in sorted(S.get(n, []), key=lambda c: -c["jev"])) if isart(p) and s >= REL][:cap]
            sv = [{"url": p, "score": s} for p, s in ((c["path"], c["jev"]) for c in sorted(S.get(n, []), key=lambda c: -c["jev"])) if p.startswith("/services/") and s >= REL][:3]
            if a: e["articles"] = a
            if sv: e["services"] = sv
            if e: links[n] = e; changed += 1
        donors = donors_for([n for n in new_pages if n in posts], P, F, cfg, posts)
        for n, ds in donors.items():
            for d in ds:
                lst = links.setdefault(d, {}).setdefault("articles", [])
                if all(x["url"] != n for x in lst):
                    lst.insert(0, {"url": n, "score": 0.9}); del lst[cap:]; changed += 1
        doc.setdefault("how", "Built by the internal-linking pipeline; refreshed weekly."); doc["generated"] = time.strftime("%Y-%m-%d")
    else:
        rel = doc.setdefault("related", {})
        for n in new_pages:
            if n not in posts: continue
            lst = [slug_of(name, p) for p in picks(n, isart)][:cap]
            if lst: rel[slug_of(name, n)] = lst; changed += 1
        donors = donors_for([n for n in new_pages if n in posts], P, F, cfg, posts)
        for n, ds in donors.items():
            for d in ds:
                lst = rel.setdefault(slug_of(name, d), [])
                if slug_of(name, n) not in lst:
                    lst.insert(0, slug_of(name, n)); del lst[cap:]; changed += 1
        doc["generated"] = time.strftime("%Y-%m-%d")
        # a slug that no longer exists (merged or unpublished) leaves every list
        alive = {slug_of(name, p) for p in posts}
        for k in list(rel):
            rel[k] = [x for x in rel[k] if x in alive]
    if changed and not CHECK:
        path.parent.mkdir(parents=True, exist_ok=True); json.dump(doc, open(path, "w"), indent=1)
    return changed

def verify_static(wt):
    r = sh(["git", "-C", str(wt), "-c", "core.quotepath=false", "diff", "--name-only"]); files = [f.strip().strip('"') for f in r.stdout.splitlines() if f.strip().endswith(".html")]
    A = re.compile(r'<a href="(/[^"]*)">([^<]*)</a>'); B = re.compile(r'<section class="ilm-related".*?</section>', re.S)
    for f in files:
        old = sh(["git", "-C", str(wt), "show", f"HEAD:{f}"]).stdout; new = (wt / f).read_text()
        if A.sub(lambda m: m.group(2), B.sub("", new)) != A.sub(lambda m: m.group(2), B.sub("", old)):
            raise RuntimeError(f"non-additive change in {f}")
    return len(files)

def commit_push(wt, msg, paths):
    sh(["git", "-C", str(wt), "add", "-A"] + paths)
    if not sh(["git", "-C", str(wt), "status", "--porcelain"]).stdout.strip(): return False
    sh(["git", "-C", str(wt), "commit", "-q", "-m", msg + "\n\nCo-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"])
    last = None
    for attempt in range(4):                       # main can move under us, and GitHub can time out
        try:
            sh(["git", "-C", str(wt), "fetch", "-q", "origin"]); sh(["git", "-C", str(wt), "rebase", "-q", "origin/main"])
            sh(["git", "-C", str(wt), "push", "-q", "origin", "HEAD:main"]); return True
        except RuntimeError as e:
            last = e; log(f"  push attempt {attempt + 1} failed: {str(e)[-160:]}"); time.sleep(30 * (attempt + 1))
    raise last

def run_site(name):
    cfg = json.load(open(D / "sites" / f"{name}.json")); repo = cfg["repo"]
    O = pathlib.Path(cfg["out"]); O.mkdir(parents=True, exist_ok=True)
    wt = fresh_worktree(repo, name)
    cfg_run = dict(cfg); cfg_run["repo"] = str(wt)
    if "webroot" in cfg:
        mirror(cfg, name); cfg_run["webroot"] = str(D / "mirror" / name)
    else:
        cfg_run["webroot"] = str(wt)
    cfg_path = O / "run.json"; json.dump(cfg_run, open(cfg_path, "w"))
    prev = set(json.load(open(O / "pages.json"))) if (O / "pages.json").exists() else set()
    if (O / "pages.json").exists(): shutil.copy(O / "pages.json", O / "pages.prev.json")
    run_stage(cfg_path, "crawl")
    P = json.load(open(O / "pages.json"))
    if name in STATIC and cfg_run["webroot"] != str(wt):
        # crawled from the live mirror, but edits go into the worktree: point each page that
        # exists in the repo at its repo file (CleaningCo: static posts in git, the rest in Supabase)
        for p, pg in P.items():
            rel = "index.html" if p == "/" else p.lstrip("/") + "/index.html"
            if (wt / rel).exists():
                pg["file"] = rel
                pg["tpl"] = "article" if cfg.get("edit_marker") and cfg["edit_marker"] in (wt / rel).read_text() else "page"
        json.dump(P, open(O / "pages.json", "w"))
    new = set(P) if FULL or not prev else set(P) - prev
    log(f"{name}: {len(P)} pages, {len(new)} new")
    if not new:
        sh(["git", "-C", repo, "worktree", "remove", "--force", str(wt)], check=False); return "nothing new"
    run_stage(cfg_path, "profile"); run_stage(cfg_path, "score", only=new)
    touched = []
    if name in STATIC:
        run_stage(cfg_path, "plan", only=new); run_stage(cfg_path, "apply", only=new); run_stage(cfg_path, "rescue")
        n = verify_static(wt); touched += ["."]; log(f"  static edits verified additive on {n} files")
    if name in MAP:
        changed = rebuild_map(name, cfg_run, wt, new); touched.append(MAP[name]["file"]); log(f"  map entries changed: {changed}")
        if name == "searchblueprint" and changed and not CHECK:
            sh(["npm", "ci", "--no-audit", "--no-fund"], cwd=wt); sh(["npx", "vitest", "run", "src/app/blog/__tests__"], cwd=wt)
    if CHECK:
        log(f"  check only: {sh(['git', '-C', str(wt), 'status', '--porcelain']).stdout.count(chr(10))} files would change"); return "check"
    msg = f"improve: internal links for {len(new)} new page{'s' if len(new) != 1 else ''}, picked by meaning\n\nWeekly internal-linking refresh: new pages profiled and scored by Jev, given their related picks, and offered to two donors each."
    pushed = commit_push(wt, msg, touched)
    sh(["git", "-C", repo, "worktree", "remove", "--force", str(wt)], check=False)
    return "pushed" if pushed else "no change"

def main():
    results = {}
    for name in NAMES:
        try:
            results[name] = run_site(name)
        except Exception as e:
            results[name] = f"FAILED: {str(e)[:300]}"; log(f"{name} FAILED: {e}")
    log("summary: " + ", ".join(f"{k}={v[:40]}" for k, v in results.items()) + f" | {jev.report()}")
    if not any(v.startswith("FAILED") for v in results.values()) and not CHECK:
        st = HOME / ".local/state/internal-linking"; st.mkdir(parents=True, exist_ok=True)
        (st / "last-ok").write_text(time.strftime("%Y-%m-%d %H:%M") + "\n")
    return 1 if any(v.startswith("FAILED") for v in results.values()) else 0

if __name__ == "__main__":
    sys.exit(main())
