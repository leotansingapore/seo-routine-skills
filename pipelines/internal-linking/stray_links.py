"""Mid-sentence links that point at /contact: Jev picks the page the phrase promises.
Run from a repo root. Usage: stray_links.py <out.json> [--apply]"""
import re, glob, json, sys, pathlib, collections, concurrent.futures as cf
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import jev
KEEP = "keep the contact page"

def pages():
    sm = open("sitemap.xml", encoding="utf-8").read()
    out = {}
    for u in re.findall(r"<loc>([^<]+)</loc>", sm):
        p = re.sub(r"https?://[^/]+", "", u).rstrip("/") or "/"
        f = (p.lstrip("/") + "/index.html") if p != "/" else "index.html"
        if pathlib.Path(f).exists():
            s = open(f, encoding="utf-8").read()
            t = re.search(r"<title[^>]*>(.*?)</title>", s, re.S)
            h1 = re.search(r"<h1[^>]*>(.*?)</h1>", s, re.S)
            out[p] = {"title": re.sub(r"\s+", " ", t.group(1)).strip() if t else p,
                      "heading": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", h1.group(1))).strip() if h1 else ""}
    return out

def collect():
    items = []
    for f in sorted(glob.glob("**/*.html", recursive=True)):
        s = open(f, encoding="utf-8").read()
        title = (re.search(r"<title[^>]*>(.*?)</title>", s, re.S) or [None, ""])[1].strip()
        for m in re.finditer(r'<a\b[^>]*href="(/contact[^"]*)"[^>]*>(.*?)</a>', s, re.S):
            lab = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(2))).strip()
            if lab in ("Contact", "Contact Us"):
                continue
            before = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s[max(0, m.start() - 600):m.start()]))[-240:]
            items.append({"file": f, "page_title": title, "label": lab, "before": before, "span": m.group(0), "href": m.group(1)})
    return items

def decide(items, P, shortlist):
    def one(it):
        cands = shortlist(it)
        crit = {p: {"title": P[p]["title"], "heading": P[p]["heading"]} for p in cands if p in P}
        crit[KEEP] = "The phrase is an invitation to get in touch, so the contact page is right."
        st = {"page": {"title": it["page_title"]}, "text_before_the_link": it["before"], "link_phrase": it["label"]}
        q = {"target": {"type": "choice", "instructions": "A reader clicks the underlined `link_phrase` in this sentence. Which page do they expect to land on? Judge by what the phrase itself promises.", "criteria": crit}}
        a = jev.ask(st, q, label=f"{it['file']} {it['label'][:30]}")
        if a:
            it["target"] = a["target"]["choice"]; it["confidence"] = round(a["target"]["confidence"], 3)
        return it
    with cf.ThreadPoolExecutor(5) as ex:
        return list(ex.map(one, items))
