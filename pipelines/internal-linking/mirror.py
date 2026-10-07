#!/usr/bin/env python3
"""Mirror a live site's sitemap URLs to <out>/<path>/index.html so site_run.py can crawl a
server-rendered app it cannot read from disk. Read-only GETs, 4 at a time."""
import sys, re, pathlib, urllib.request, concurrent.futures as cf
base, out = sys.argv[1].rstrip("/"), pathlib.Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"}
def get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40) as r:
        return r.read().decode("utf-8", "replace")
sm = get(base + "/sitemap.xml"); (out / "sitemap.xml").write_text(sm)
urls = re.findall(r"<loc>([^<]+)</loc>", sm)
def one(u):
    p = re.sub(r"^https?://[^/]+", "", u).split("?")[0].rstrip("/") or "/"
    f = out / ("index.html" if p == "/" else p.lstrip("/") + "/index.html")
    try:
        html = get(u); f.parent.mkdir(parents=True, exist_ok=True); f.write_text(html); return None
    except Exception as e:
        return f"{p}: {e}"
with cf.ThreadPoolExecutor(4) as ex:
    errs = [e for e in ex.map(one, urls) if e]
print(f"mirrored {len(urls) - len(errs)} of {len(urls)} from {base}")
for e in errs[:8]: print("  FAIL", e)
