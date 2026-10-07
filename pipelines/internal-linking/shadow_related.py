#!/usr/bin/env python3
"""Score a site's existing related-module links with the same question as the candidates, and
report current vs best available. Usage: shadow_related.py <config.json> [blog_prefix]"""
import json, sys, pathlib, statistics, collections, concurrent.futures as cf
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import jev
from score_links import question
cfg = json.load(open(sys.argv[1])); pre = sys.argv[2] if len(sys.argv) > 2 else "/blog/"
O = pathlib.Path(cfg["out"])
P = json.load(open(O / "pages.json")); F = json.load(open(O / "profiles.json")); L = json.load(open(O / "links.json")); S = json.load(open(O / "link_scores.json"))
def sstate(p):
    pg, pr = P[p], F[p]
    return {"site": cfg["business"], "source_page": {"url": p, "title": pg["title"], "heading": pg["h1"], "meta_description": pg["desc"],
            "section_headings": pg["h2s"], "what_it_is": f"{pr['role']} about {pr['cluster']}", "text": pg["sample"][:1200]}}
rel = collections.defaultdict(list)
for l in L:
    if l["kind"] == "related" and l["src"] in F and l["dst"] in F and l["dst"] not in rel[l["src"]]:
        rel[l["src"]].append(l["dst"])
def one(s):
    qs = {}
    for i, d in enumerate(rel[s][:12]):
        r, c = question(P[d], F[d]); qs[f"r{i}"], qs[f"c{i}"] = r, c
    a = jev.ask(sstate(s), qs, label=f"shadow {s}")
    return s, [{"path": d, "jev": round(a[f"r{i}"]["noul"], 3), "competes": round(a[f"c{i}"]["noul"], 3)} for i, d in enumerate(rel[s][:12]) if a and a.get(f"r{i}")]
with cf.ThreadPoolExecutor(5) as ex:
    res = dict(ex.map(one, [s for s in rel]))
json.dump(res, open(O / "existing_related.json", "w"))
cur = [c["jev"] for v in res.values() for c in v]
best = []
for s in rel:
    pool = {c["path"]: c for c in S.get(s, []) if c["path"].startswith(pre)}
    for c in res.get(s, []): pool.setdefault(c["path"], c)
    best += [c["jev"] for c in sorted([c for c in pool.values() if c["competes"] < 0.45 and c["jev"] >= 0.55], key=lambda c: -c["jev"])[:len(rel[s])]]
f = lambda v: f"median {statistics.median(v):.2f}, below 0.3 {100*sum(1 for x in v if x<0.3)/len(v):.0f}%, 0.75+ {100*sum(1 for x in v if x>=0.75)/len(v):.0f}%" if v else "n/a"
print(f"[shadow] pages with a related block {len(rel)}, links {len(cur)} | current: {f(cur)} | best available: {f(best)} | {jev.report()}")
