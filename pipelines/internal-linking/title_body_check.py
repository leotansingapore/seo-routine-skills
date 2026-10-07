"""For each page whose title misses a striking-distance query, ask Jev whether the
page BODY answers that query. Only covered queries may go into a new title.
Usage: title_body_check.py <gap.json> <out.json> [min_vol] [min_missvol]"""
import json, sys, re, html, pathlib, concurrent.futures as cf, urllib.request
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import jev
from lxml import html as LH

def body_text(url):
    req = urllib.request.Request(url.rstrip("/") if url.count("/") > 3 else url, headers={"User-Agent": "Mozilla/5.0 (compatible; seo-check)"})
    h = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    doc = LH.fromstring(h)
    for junk in doc.xpath("//script|//style|//nav|//header|//footer|//noscript"):
        junk.drop_tree()
    root = (doc.xpath("//main") or doc.xpath("//article") or doc.xpath("//body"))[0]
    heads = [re.sub(r"\s+", " ", x.text_content()).strip() for x in root.xpath(".//h1|.//h2|.//h3")]
    text = re.sub(r"\s+", " ", root.text_content()).strip()
    return heads[:40], text[:9000]

def main(gap_file, out_file, min_vol=90, min_missvol=300):
    gap = json.load(open(gap_file)); todo = []
    seen = set()
    for url, v in gap.items():
        if "error" in v: continue
        key = url.rstrip("/")
        if key in seen: continue
        seen.add(key)
        miss = [q for q in v["queries"] if q["match"] < 0.5 and q["vol"] >= int(min_vol)]
        if miss and (v["queries"][0]["match"] < 0.5 or sum(q["vol"] for q in miss) >= int(min_missvol)):
            todo.append((url, v, miss))
    print(f"{len(todo)} pages to check", flush=True)
    def one(t):
        url, v, miss = t
        try:
            heads, text = body_text(url)
        except Exception as e:
            return url, {**v, "error": f"body fetch: {e}"}
        state = {"page": {"url": url, "title": v["title"], "headings": heads, "text": text}}
        qs = {f"q{i}": {"type": "noul", "instructions": f"Someone searched Google for \"{q['q']}\". Does this `page` actually give them what that search is looking for? Judge the content, not the title. A page that only mentions the words in passing does not."} for i, q in enumerate(miss)}
        a = jev.ask(state, qs, label=url)
        if not a:
            return url, {**v, "error": "jev failed"}
        for i, q in enumerate(miss):
            q["covered"] = round(a[f"q{i}"]["noul"], 3)
        return url, {**v, "missed": miss}
    res = {}
    with cf.ThreadPoolExecutor(5) as ex:
        for url, r in ex.map(one, todo):
            res[url] = r
    json.dump(res, open(out_file, "w"), indent=1)
    print(jev.report())

if __name__ == "__main__":
    main(*sys.argv[1:])
