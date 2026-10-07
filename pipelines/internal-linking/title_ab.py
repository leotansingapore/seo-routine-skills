"""Old vs new search snippet, judged by Jev on every query the page ranks for
(positions 1-20, top 10 by volume). Usage: title_ab.py <drafts.json> <gap.json...> -- <rank.json...> <out.json>"""
import json, sys, pathlib, collections, concurrent.futures as cf
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import jev
from title_gap import items_of

args = sys.argv[1:]; i = args.index("--")
drafts = json.load(open(args[0])); gaps = {}
for g in args[1:i]: gaps.update(json.load(open(g)))
ranks = args[i+1:-1]; out_file = args[-1]
by = collections.defaultdict(list)
for rf in ranks:
    for it in items_of(rf):
        se = it["ranked_serp_element"]["serp_item"]
        if se.get("type") == "organic" and se.get("rank_group", 99) <= 20:
            by[se["url"].rstrip("/")].append({"q": it["keyword_data"]["keyword"], "vol": it["keyword_data"]["keyword_info"].get("search_volume") or 0, "pos": se["rank_group"]})

def ask(title, desc, qs, label):
    state = {"search_result": {"title": title, "description": desc or ""},
             "note": "This is how the page appears in Google results. The searcher sees only this title and description."}
    q = {f"q{k}": {"type": "noul", "instructions": f"A person searched Google for \"{x['q']}\". Seeing only this `search_result`, would they believe the page answers what they searched for?"} for k, x in enumerate(qs)}
    a = jev.ask(state, q, label=label)
    return [round(a[f"q{k}"]["noul"], 3) for k in range(len(qs))] if a else None

def one(url):
    g = gaps[url]; d = drafts[url]
    qs = sorted({x["q"]: x for x in by[url.rstrip("/")]}.values(), key=lambda x: -x["vol"])[:10]
    old = ask(g["title"], g.get("desc"), qs, "old " + url)
    new_title = d["title"] + (" - FinanceBlog Blog" if "financeblog" in url else " — InternshipSite")
    new = ask(new_title, d["desc"] or g.get("desc"), qs, "new " + url)
    return url, [{**x, "old": o, "new": n} for x, o, n in zip(qs, old or [], new or [])]

res = {}
with cf.ThreadPoolExecutor(5) as ex:
    for url, rows in ex.map(one, list(drafts)):
        res[url] = rows
        vol_old = sum(r["vol"] for r in rows if r["old"] >= 0.6); vol_new = sum(r["vol"] for r in rows if r["new"] >= 0.6)
        lost = [f"{r['q']} ({r['old']:.2f}->{r['new']:.2f})" for r in rows if r["old"] >= 0.6 and r["new"] < 0.6]
        print(f"{url.split('/')[-1]}: matched volume {vol_old} -> {vol_new}" + (f"  LOST: {'; '.join(lost)}" if lost else ""), flush=True)
json.dump(res, open(out_file, "w"), indent=1)
print(jev.report())
