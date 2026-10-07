#!/usr/bin/env python3
"""Backlink data for audits, from DataForSEO through the local OpenSEO app (http://localhost:3001/mcp).

  backlinks.py overview <domain>   totals, spam score, monthly trend, new/lost per month (~$0.08 fresh)
  backlinks.py links <domain>      strongest link from each referring domain, top 100 (~$0.03 fresh)

Every answer is cached per domain for 20 days and a cached answer costs nothing, so call it freely. Fresh fetches are
capped at 20 a day across all domains (exit 5 when used up). Exit 4 when OpenSEO is not running: record backlinks as
Needs external data. Output is JSON on stdout. Built 2026-10-06; spend lands on the shared DataForSEO balance."""
import datetime, json, os, re, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "state", "backlinks-cache")
LEDGER = os.path.join(ROOT, "state", "backlinks-fetches.jsonl")
MCP = "http://localhost:3001/mcp"
TTL_DAYS, DAILY_CAP, PROJECT = 20, 20, "seo-visibility audits"


def call(name, args):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}
    req = urllib.request.Request(MCP, data=json.dumps(body).encode(), headers={
        "content-type": "application/json", "accept": "application/json,text/event-stream", "MCP-Protocol-Version": "2025-06-18"})
    d = json.load(urllib.request.urlopen(req, timeout=180))
    if "error" in d or d["result"].get("isError"):
        raise RuntimeError(str(d.get("error") or d["result"]["content"][0]["text"])[:300])
    return d["result"].get("structuredContent") or {}


def project_id():
    for p in call("list_projects", {})["projects"]:
        if p["name"] == PROJECT:
            return p["id"]
    return call("create_project", {"name": PROJECT, "locationCode": 2702, "languageCode": "en"})["project"]["id"]


def fresh_today(now):
    try:
        return sum(1 for l in open(LEDGER) if json.loads(l)["date"] == now.date().isoformat())
    except OSError:
        return 0


def shrink(kind, r):
    if kind == "overview":
        o = r["overview"]["overview"]
        return {"target": o["target"], "summary": o["summary"], "trends": o["trends"][-12:], "newLost": o["newLostTrends"][-12:]}
    b = r["backlinks"]
    keep = ("domainFrom", "urlFrom", "urlTo", "anchor", "isDofollow", "domainFromRank", "spamScore", "firstSeen", "isLost", "isBroken")
    return {"target": r["target"], "referringDomainsTotal": b["totalCount"],
            "rows": [{k: x.get(k) for k in keep} for x in b["rows"]]}


def main(argv):
    if len(argv) != 2 or argv[0] not in ("overview", "links"):
        print(__doc__, file=sys.stderr)
        return 2
    kind = argv[0]
    domain = re.sub(r"^https?://", "", argv[1].strip().lower()).split("/")[0]
    domain = domain[4:] if domain.startswith("www.") else domain
    if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", domain):
        print("not a domain: %r" % argv[1], file=sys.stderr)
        return 2
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, "%s-%s.json" % (kind, domain))
    now = datetime.datetime.now()
    if os.path.exists(f) and time.time() - os.path.getmtime(f) < TTL_DAYS * 86400:
        out = json.load(open(f))
        out["cached_from"] = datetime.date.fromtimestamp(os.path.getmtime(f)).isoformat()
        print(json.dumps(out, indent=1))
        return 0
    if fresh_today(now) >= DAILY_CAP:
        print("daily cap of %d fresh fetches used; cached domains still answer" % DAILY_CAP, file=sys.stderr)
        return 5
    try:
        pid = project_id()
        if kind == "overview":
            r = call("get_backlinks_overview", {"projectId": pid, "target": domain})
        else:
            r = call("get_backlinks_profile", {"projectId": pid, "target": domain, "mode": "one_per_domain", "pageSize": 100})
    except (OSError, urllib.error.URLError) as e:
        print("no_access: OpenSEO is not reachable at %s (%s)" % (MCP, e), file=sys.stderr)
        return 4
    except RuntimeError as e:
        print("OpenSEO refused: %s" % e, file=sys.stderr)
        return 3
    with open(LEDGER, "a") as fh:
        fh.write(json.dumps({"date": now.date().isoformat(), "kind": kind, "domain": domain}) + "\n")
    json.dump(r, open(f + ".raw", "w"))  # paid for: keep it even if shrink() breaks on a new OpenSEO shape
    out = shrink(kind, r)
    json.dump(out, open(f, "w"))
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
