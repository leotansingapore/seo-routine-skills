#!/usr/bin/env python3
"""Pass 2: Jev rates every shortlisted target for one source page.

One Noul per candidate, all candidates for a source asked in a single request so the
source page's text is charged once. The model never picks the candidates and never
writes an anchor here; it answers one question about one pair.
"""
import json, sys, pathlib, collections, concurrent.futures as cf
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import jev, candidates as C

OUT = pathlib.Path(".")
BUSINESS = ("D'Marketing Agency is a Singapore digital marketing agency. Its website has service "
            "pages that sell its services and a large blog of marketing guides. Both are on the "
            "same site, so a link between them is an internal link.")

def source_state(pg, prof):
    return {"site": BUSINESS,
            "source_page": {"url": pg["path"], "title": pg["title"], "heading": pg["h1"],
                            "meta_description": pg["desc"], "section_headings": pg["h2s"],
                            "what_it_is": f"{prof['role']} about {prof['cluster']}",
                            "text": pg["sample"][:1200]}}

def question(tgt_pg, tgt_prof):
    """Two judgments per candidate. One wording could not catch both failure shapes:
    a link planted in text about something else, and a link to a page that is really
    the same article. Relevance decides the link; competition is a separate flag."""
    tgt = {"url": tgt_pg["path"], "title": tgt_pg["title"], "heading": tgt_pg["h1"],
           "meta_description": tgt_pg["desc"], "section_headings": tgt_pg["h2s"][:8],
           "what_it_is": f"{tgt_prof['role']} about {tgt_prof['cluster']}"}
    relevant = {"type": "noul",
      "instructions": {"link_target": tgt,
        "question": ("Would a link to `link_target` belong inside the text of `source_page`? "
                     "Judge whether `source_page` actually covers, or explicitly raises, the "
                     "subject `link_target` is about.")},
      "criteria": {
        "true": ("`source_page` deals with the subject of `link_target` directly, or names it as a "
                 "step, a tool, a cause, a cost or a next move. A reader part-way through "
                 "`source_page` would recognise the link as being about what they are reading. "
                 "This includes the agency's service page for a job `source_page` explains how to do."),
        "false": ("`link_target` is about a different subject. The only thing connecting the two is "
                  "that both are marketing topics, or both are published by the same agency. Putting "
                  "the link on `source_page` would mean planting it in text about something else.")}}
    competes = {"type": "noul",
      "instructions": {"link_target": tgt,
        "question": ("Do `source_page` and `link_target` set out to answer the same question for the "
                     "same reader?")},
      "criteria": {
        "true": ("Both pages cover the same subject at the same depth and would be written from the "
                 "same brief. A reader who has read one has little reason to read the other, and in "
                 "search results the two compete with each other."),
        "false": ("The pages cover different subjects, or one goes deeper, narrower or wider than the "
                  "other, so a reader gains something by reading both.")}}
    return relevant, competes

def run(sources, P, F, vec, existing, workers=10, verbose=False):
    results = {}
    def one(s):
        cands = C.shortlist(s, P, F, vec, existing)
        if not cands:
            return s, []
        qs = {}
        for i, c in enumerate(cands):
            rel, cmp_ = question(P[c["path"]], F[c["path"]])
            qs[f"r{i}"] = rel
            qs[f"c{i}"] = cmp_
        a = jev.ask(source_state(P[s], F[s]), qs, label=f"links {s}")
        if not a:
            return s, None
        out = []
        for i, c in enumerate(cands):
            r_, c_ = a.get(f"r{i}"), a.get(f"c{i}")
            if r_ and c_:
                out.append({**c, "jev": round(r_["noul"], 3), "competes": round(c_["noul"], 3)})
        out.sort(key=lambda x: -x["jev"])
        return s, out
    with cf.ThreadPoolExecutor(workers) as ex:
        for i, (s, r) in enumerate(ex.map(one, sources), 1):
            if r is not None:
                results[s] = r
            if i % 25 == 0:
                print(f"  {i}/{len(sources)} {jev.report()}", flush=True)
    return results

if __name__ == "__main__":
    P = json.load(open(OUT / "pages.json")); F = json.load(open(OUT / "profiles.json"))
    L = json.load(open(OUT / "links.json"))
    existing = collections.defaultdict(set)
    for l in L:
        existing[l["src"]].add(l["dst"])
    vec = C.build(P, F)
    probe = "--probe" in sys.argv
    srcs = (["/blog/10-effective-off-page-seo-techniques", "/seo-agency-singapore",
             "/blog/business-name-ideas"] if probe else [p for p in P if p in F])
    r = run(srcs, P, F, vec, existing, workers=3 if probe else 10)
    if probe:
        for s in srcs:
            print(f"\n=== {s}")
            for c in r.get(s, []):
                print(f"   rel={c['jev']:.2f} dup={c['competes']:.2f} sim={c['sim']:.3f} {c['why'][:20]:20s} {c['path'][:66]}")
    else:
        json.dump(r, open(OUT / "link_scores.json", "w"), indent=0)
        print("wrote link_scores.json", len(r))
    print(jev.report())
