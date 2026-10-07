"""PageSpeed Insights (mobile) summary for a list of URLs: score, LCP, TBT, CLS,
the LCP element and the top opportunities. No key needed at this volume."""
import json, sys, urllib.request, urllib.parse, time
def run(url, strategy="mobile"):
    q=urllib.parse.urlencode({"url":url,"strategy":strategy,"category":"performance"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen("https://www.googleapis.com/pagespeedonline/v5/runPagespeed?"+q, timeout=120) as r:
                return json.load(r)
        except Exception as e:
            last=e; time.sleep(5)
    return {"error":str(last)}
def summarize(url, d):
    if "error" in d: return f"{url}: ERROR {d['error'][:120]}"
    lh=d["lighthouseResult"]; a=lh["audits"]
    score=round(lh["categories"]["performance"]["score"]*100)
    lcp=a["largest-contentful-paint"]["displayValue"]; tbt=a["total-blocking-time"]["displayValue"]; cls=a["cumulative-layout-shift"]["displayValue"]
    fcp=a["first-contentful-paint"]["displayValue"]; si=a["speed-index"]["displayValue"]
    el=""
    try:
        items=a["largest-contentful-paint-element"]["details"]["items"]
        node=items[0]["items"][0]["node"] if "items" in items[0] else items[0]["node"]
        el=(node.get("snippet") or node.get("selector") or "")[:110]
    except Exception: pass
    opps=[]
    for k,v in a.items():
        det=v.get("details") or {}
        ms=det.get("overallSavingsMs") or 0; kb=(det.get("overallSavingsBytes") or 0)/1024
        if det.get("type")=="opportunity" and (ms>=150 or kb>=100):
            opps.append((ms,kb,v["title"]))
    opps.sort(reverse=True)
    tot=a.get("total-byte-weight",{}).get("displayValue","")
    out=f"{url}\n  score {score}  LCP {lcp}  FCP {fcp}  TBT {tbt}  CLS {cls}  SI {si}  weight {tot}\n  LCP element: {el}"
    for ms,kb,t in opps[:5]: out+=f"\n  - {t}: {ms:.0f} ms, {kb:.0f} KB"
    return out
if __name__=="__main__":
    strategy="mobile"
    urls=[u for u in sys.argv[1:] if not u.startswith("--")]
    if "--desktop" in sys.argv: strategy="desktop"
    for u in urls:
        print(summarize(u, run(u,strategy)), flush=True)
