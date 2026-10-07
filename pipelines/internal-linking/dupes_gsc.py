"""Duplicate candidates from Search Console: pages that show for the same queries.
Jev judges each pair (same question for the same reader?). Usage:
dupes_gsc.py <gsc.json> <pages.json> <host> <out.json> [min_shared_imp]"""
import json, sys, collections, itertools, pathlib, concurrent.futures as cf
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import jev

def main(gsc_file, pages_file, host, out_file, min_shared=30):
    rows = json.load(open(gsc_file))["rows"]; P = json.load(open(pages_file))
    def path(u):
        p = u.split(host, 1)[-1].split("#")[0].split("?")[0].rstrip("/") or "/"
        return p
    byq = collections.defaultdict(dict)
    for r in rows:
        q, u = r["keys"]; p = path(u)
        byq[q][p] = byq[q].get(p, 0) + r["impressions"]
    pair = collections.Counter(); pairq = collections.defaultdict(list)
    for q, pages in byq.items():
        for a, b in itertools.combinations(sorted(pages), 2):
            w = min(pages[a], pages[b]); pair[(a, b)] += w; pairq[(a, b)].append((w, q))
    cands = [(ab, w) for ab, w in pair.items() if w >= int(min_shared) and ab[0] in P and ab[1] in P]
    missing = {p for ab, w in pair.items() if w >= int(min_shared) for p in ab if p not in P}
    print(f"{len(cands)} candidate pairs; pages not in the crawl: {sorted(missing)[:10]}", flush=True)
    def prof(p):
        x = P[p]; return {"url": p, "title": x["title"], "heading": x["h1"], "meta_description": x["desc"],
                          "section_headings": (eval(x["h2s"]) if isinstance(x["h2s"], str) else x["h2s"])[:12], "words": x["words"], "opening": x["sample"][:600]}
    def one(c):
        (a, b), w = c
        st = {"site": "Catalyst Immigration, a Singapore immigration consultancy", "page_a": prof(a), "page_b": prof(b)}
        q = {"dup": {"type": "noul", "instructions": "Do `page_a` and `page_b` answer the same main question for the same reader, so that a reader who finds either one would be fully served by the other? Pages on related but different questions (for example PR eligibility versus the PR application steps, or a guide versus a paid service page) are not duplicates."}}
        a_ = jev.ask(st, q, label=f"{a} | {b}")
        top = [qq for _, qq in sorted(pairq[(a, b)], reverse=True)[:5]]
        return {"a": a, "b": b, "shared_imp": w, "queries": top, "dup": round(a_["dup"]["noul"], 3) if a_ else None}
    with cf.ThreadPoolExecutor(5) as ex:
        res = list(ex.map(one, cands))
    res.sort(key=lambda r: -(r["dup"] or 0))
    json.dump(res, open(out_file, "w"), indent=1)
    print(jev.report())

if __name__ == "__main__":
    main(*sys.argv[1:])
