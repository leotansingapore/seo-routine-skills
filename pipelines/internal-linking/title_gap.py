"""Striking-distance title check. For each page ranking 4-20 on queries with
volume, Jev judges whether the live title + description tell that searcher the
page answers their search. Usage: title_gap.py <rank.json> <out.json> [min_vol]"""
import json, sys, re, html, collections, concurrent.futures as cf, pathlib, urllib.request
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import jev

def items_of(f):
    d = json.load(open(f)); out = []
    for t in d.get("tasks", []):
        for r in (t.get("result") or []):
            out += r.get("items") or []
    return out

def live_meta(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; seo-check)"})
        h = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    except Exception as e:
        return None, None
    t = re.search(r"<title[^>]*>(.*?)</title>", h, re.S)
    d = re.search(r'<meta name="description" content="([^"]*)"', h) or re.search(r"<meta name=\"description\" content='([^']*)'", h)
    return (html.unescape(t.group(1).strip()) if t else None, html.unescape(d.group(1)) if d else None)

def main(rank_file, out_file, min_vol=50):
    by = collections.defaultdict(list)
    for i in items_of(rank_file):
        se = i["ranked_serp_element"]["serp_item"]; kw = i["keyword_data"]["keyword"]
        vol = i["keyword_data"]["keyword_info"].get("search_volume") or 0
        if se.get("type") == "organic" and 4 <= se.get("rank_group", 99) <= 20 and vol >= int(min_vol):
            by[se["url"]].append({"q": kw, "vol": vol, "pos": se["rank_group"]})
    pages = sorted(by, key=lambda u: -sum(x["vol"] for x in by[u]))
    print(f"{len(pages)} pages with striking-distance queries", flush=True)
    def one(url):
        qs = sorted(by[url], key=lambda x: -x["vol"])[:5]
        title, desc = live_meta(url)
        if title is None:
            return url, {"error": "fetch failed", "queries": qs}
        state = {"search_result": {"title": title, "description": desc or ""},
                 "note": "This is how the page appears in Google results. The searcher sees only this title and description."}
        questions = {f"q{k}": {"type": "noul", "instructions": f"A person searched Google for \"{x['q']}\". Seeing only this `search_result`, would they believe the page answers what they searched for?"} for k, x in enumerate(qs)}
        a = jev.ask(state, questions, label=url)
        if not a:
            return url, {"error": "jev failed", "title": title, "queries": qs}
        for k, x in enumerate(qs):
            x["match"] = round(a[f"q{k}"]["noul"], 3)
        return url, {"title": title, "desc": desc, "queries": qs}
    res = {}
    with cf.ThreadPoolExecutor(5) as ex:
        for url, r in ex.map(one, pages):
            res[url] = r
    json.dump(res, open(out_file, "w"), indent=1)
    print(jev.report())

if __name__ == "__main__":
    main(*sys.argv[1:])
